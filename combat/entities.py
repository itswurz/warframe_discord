# combat/entities.py
# ─────────────────────────────────────────────────────────────────────────────
# Three classes:
#   Entity         — shared HP / shields / armor / energy / status logic
#   WarframeEntity — player-controlled; tracks combo_gauge, passive flags
#   EnemyEntity    — AI-controlled; faction, behavior, ability selection
#
# Damage model:
#   armor_reduction = armor / (armor + 300)
#   effective_damage = raw * (1 - armor_reduction)
#   Slash DoT, Toxin, and True damage bypass armor entirely.
#   Toxin DoT also bypasses shields.
#   Magnetize doubles ALL damage received.
#   Viral halves effective max HP (damage ignores HP above the threshold).
#   Shields absorb damage before HP (except bypass_shields=True / Toxin).
#   Heat applies -50% armor while burning (magnitude stored in status).
#   Cold applies -30% damage output (checked in choose_action / _hit_enemy).
#   Corrosive permanently strips stored base armor (up to 4 stacks).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import random
from typing import Optional
from combat.status import (
    StatusEffect, StatusType,
    make_slash_bleed, make_knockdown,
    dmg_icon,
)


class Entity:
    """Base combatant. Handles all damage, healing, and status bookkeeping."""

    def __init__(
        self,
        name:       str,
        hp:         int,
        shields:    int,
        armor:      int,
        energy:     int,
        max_energy: int,
    ) -> None:
        self.name        = name
        self.max_hp      = hp
        self.hp          = hp
        self.max_shields = shields
        self.shields     = shields
        self.base_armor  = armor
        self.armor       = armor
        self.max_energy  = max_energy
        self.energy      = max_energy
        self.statuses:   list[StatusEffect] = []

    # ── Query helpers ──────────────────────────────────────────────────────────

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    def has_status(self, stype: StatusType) -> bool:
        return any(s.status_type == stype for s in self.statuses)

    def get_status(self, stype: StatusType) -> Optional[StatusEffect]:
        for s in self.statuses:
            if s.status_type == stype:
                return s
        return None

    def can_act(self) -> bool:
        blocking = (
            StatusType.KNOCKDOWN,
            StatusType.BLIND,
            StatusType.STUNNED,
            StatusType.MAGNETIZED,
        )
        return self.is_alive and not any(self.has_status(b) for b in blocking)

    def is_confused(self) -> bool:
        rad = self.get_status(StatusType.RADIATION)
        if rad and random.random() < rad.magnitude:
            return True
        return False

    # ── Effective armor ────────────────────────────────────────────────────────

    def effective_armor(self) -> int:
        arm = self.armor
        if self.has_status(StatusType.HEAT):
            arm = int(arm * 0.50)
        return max(0, arm)

    # ── Damage ─────────────────────────────────────────────────────────────────

    def _armor_mult(self, dtype: str = "") -> float:
        arm = self.effective_armor()
        return 1.0 - (arm / (arm + 300))

    def take_damage(
        self,
        amount:         float,
        damage_type:    str  = "true",
        bypass_shields: bool = False,
    ) -> int:
        raw = float(amount)

        if damage_type not in ("true", "slash", "toxin"):
            raw *= self._armor_mult(damage_type)

        if self.has_status(StatusType.MAGNETIZED):
            raw *= 2.0

        dmg = max(1, int(raw))
        toxin_bypass = (damage_type == "toxin")

        if not bypass_shields and not toxin_bypass and self.shields > 0:
            if dmg <= self.shields:
                self.shields -= dmg
                return 0
            dmg -= self.shields
            self.shields = 0

        if self.has_status(StatusType.VIRAL):
            viral_cap = max(1, self.max_hp // 2)
            if self.hp > viral_cap:
                self.hp = viral_cap

        self.hp = max(0, self.hp - dmg)
        return dmg

    def heal_hp(self, amount: int) -> int:
        gained = min(amount, self.max_hp - self.hp)
        self.hp += gained
        return gained

    def restore_shields(self, amount: int) -> int:
        gained = min(amount, self.max_shields - self.shields)
        self.shields += gained
        return gained

    # ── Status ─────────────────────────────────────────────────────────────────

    def apply_status(self, effect: StatusEffect) -> None:
        stackable = (StatusType.HEAT, StatusType.TOXIN, StatusType.CORROSIVE)

        for existing in self.statuses:
            if existing.status_type == effect.status_type:
                if effect.status_type in stackable:
                    if existing.stacks < 4:
                        existing.stacks   += 1
                        existing.magnitude += effect.magnitude
                        existing.duration  = max(existing.duration, effect.duration)
                        if effect.status_type == StatusType.CORROSIVE:
                            strip = int(self.base_armor * effect.magnitude)
                            self.armor = max(0, self.armor - strip)
                else:
                    if effect.duration > existing.duration:
                        existing.duration  = effect.duration
                        existing.magnitude = effect.magnitude
                return

        if effect.status_type == StatusType.CORROSIVE:
            strip = int(self.base_armor * effect.magnitude)
            self.armor = max(0, self.armor - strip)

        if effect.status_type == StatusType.MAGNETIC:
            drained = min(self.shields, 50)
            self.shields = max(0, self.shields - drained)

        self.statuses.append(effect)

    def remove_status(self, stype: StatusType) -> None:
        self.statuses = [s for s in self.statuses if s.status_type != stype]

    def tick_statuses(self) -> list[str]:
        """
        Called during End Phase. Process all DoT / lingering effects,
        decrement durations, purge expired. Returns log lines.
        All emoji are read dynamically via s.icon() / dmg_icon() — no literals.
        """
        messages: list[str] = []

        for s in list(self.statuses):
            stype = s.status_type

            # ── Slash Bleed — true damage, bypasses armor & shields ────────
            if stype == StatusType.SLASH_BLEED:
                dmg = int(s.magnitude)
                self.hp = max(0, self.hp - dmg)
                messages.append(
                    f"{s.icon()} **{self.name}** bleeds for "
                    f"**{dmg}** {dmg_icon('true')} True dmg! "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Heat — fire DoT (bypasses armor, not shields) ──────────────
            elif stype == StatusType.HEAT:
                dmg = max(1, int(s.magnitude))
                self.hp = max(0, self.hp - dmg)
                stack_note = f" ×{s.stacks} stacks" if s.stacks > 1 else ""
                messages.append(
                    f"{s.icon()} **{self.name}** burns for **{dmg}** "
                    f"{dmg_icon('heat')} Heat dmg!{stack_note} "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Toxin — DoT that bypasses shields ──────────────────────────
            elif stype == StatusType.TOXIN:
                dmg = max(1, int(s.magnitude))
                self.hp = max(0, self.hp - dmg)
                stack_note = f" ×{s.stacks} stacks" if s.stacks > 1 else ""
                messages.append(
                    f"{s.icon()} **{self.name}** poisoned for **{dmg}** "
                    f"{dmg_icon('toxin')} Toxin dmg!{stack_note} "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Gas — AoE Toxin cloud ──────────────────────────────────────
            elif stype == StatusType.GAS:
                dmg = max(1, int(s.magnitude))
                self.hp = max(0, self.hp - dmg)
                messages.append(
                    f"{s.icon()} **{self.name}** inhales Gas cloud for **{dmg}** "
                    f"{dmg_icon('toxin')} Toxin dmg! "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Corrosive — permanent armor strip; no tick damage ──────────
            # (armor already stripped on application; status stays for UI display)

            # Tesla Coil, Polarize Shard, Radiation, Electric arcs
            # are resolved at the session level (needs access to other entities).

        # Decrement durations, discard expired
        # Corrosive is permanent (duration=999) — tick still runs but won't expire
        self.statuses = [s for s in self.statuses if s.tick()]
        return messages

    # ── Display ────────────────────────────────────────────────────────────────

    def hp_bar(self, length: int = 10) -> str:
        ratio  = self.hp / max(1, self.max_hp)
        filled = round(ratio * length)
        return f"{'█' * filled}{'░' * (length - filled)} {self.hp}/{self.max_hp}"

    def shield_bar(self, length: int = 8) -> str:
        if self.max_shields == 0:
            return "—"
        ratio  = self.shields / max(1, self.max_shields)
        filled = round(ratio * length)
        return f"{'█' * filled}{'░' * (length - filled)} {self.shields}/{self.max_shields}"

    def status_icons(self) -> str:
        return " ".join(str(s) for s in self.statuses) or "—"


# ── WarframeEntity ─────────────────────────────────────────────────────────────

class WarframeEntity(Entity):
    """Player-controlled Warframe. Extends Entity with combo gauge and passive tracking."""

    def __init__(
        self,
        warframe_key:  str,
        warframe_data: dict,
        mod_stats:     dict | None = None,
    ) -> None:
        stats = warframe_data["stats"]

        def _parse(val: str) -> int:
            return int(val.split("→")[0].strip().split()[0])

        def _stat(name: str) -> str:
            for k, v in stats.items():
                if k == name or k.endswith(name):
                    return v
            raise KeyError(name)

        hp      = _parse(_stat("Health"))
        shields = _parse(_stat("Shields"))
        armor   = int(_stat("Armor"))
        e_base  = _parse(_stat("Energy"))

        raw_energy = _stat("Energy")
        if "→" in raw_energy:
            parts = raw_energy.split("→")
            e_max = int(parts[1].strip().split()[0])
        else:
            e_max = e_base

        # ── Apply mod bonuses if supplied ──────────────────────────────────────
        # mod_stats comes from mods_ui.get_active_stat_bonuses() and contains
        # fully-computed final values (health, shields, armor, energy, plus
        # optional bonus keys like ability_efficiency_bonus).
        if mod_stats:
            hp      = mod_stats.get("health",  hp)
            shields = mod_stats.get("shields", shields)
            armor   = mod_stats.get("armor",   armor)
            e_base  = mod_stats.get("energy",  e_base)
            e_max   = mod_stats.get("energy",  e_max)

        super().__init__(
            name=warframe_data["name"],
            hp=hp, shields=shields, armor=armor,
            energy=e_base, max_energy=e_max,
        )

        # Store extra mod bonuses so the rest of the combat system can read them
        self.mod_stats: dict = mod_stats or {}
        self.warframe_key   = warframe_key
        self.warframe_data  = warframe_data
        self.combo_gauge    = 0

        # Generic ability-state bag
        self.ability_flags: dict = {}

    # ── Convenience properties (backwards-compat shims) ────────────────────────

    @property
    def static_charges(self) -> int:
        return self.ability_flags.get("static_charges", 0)

    @static_charges.setter
    def static_charges(self, v: int) -> None:
        self.ability_flags["static_charges"] = v

    @property
    def exalted_active(self) -> bool:
        return self.ability_flags.get("exalted_active", False)

    @exalted_active.setter
    def exalted_active(self, v: bool) -> None:
        self.ability_flags["exalted_active"] = v

    @property
    def magnetize_absorb(self) -> bool:
        return self.ability_flags.get("magnetize_absorb", False)

    @magnetize_absorb.setter
    def magnetize_absorb(self, v: bool) -> None:
        self.ability_flags["magnetize_absorb"] = v

    @property
    def magnetize_stored(self) -> int:
        return self.ability_flags.get("magnetize_stored", 0)

    @magnetize_stored.setter
    def magnetize_stored(self, v: int) -> None:
        self.ability_flags["magnetize_stored"] = v

    @property
    def speed_active(self) -> bool:
        return self.ability_flags.get("speed_active", False)

    @speed_active.setter
    def speed_active(self, v: bool) -> None:
        self.ability_flags["speed_active"] = v

    @property
    def speed_turns(self) -> int:
        return self.ability_flags.get("speed_turns", 0)

    @speed_turns.setter
    def speed_turns(self, v: int) -> None:
        self.ability_flags["speed_turns"] = v

    def energy_bar(self, length: int = 10) -> str:
        ratio  = self.energy / max(1, self.max_energy)
        filled = round(ratio * length)
        return f"{'█' * filled}{'░' * (length - filled)} {self.energy}/{self.max_energy}"

    def damage_multiplier(self) -> float:
        from combat.abilities import PASSIVE_DAMAGE_BONUS
        mult = 1.0
        fn = PASSIVE_DAMAGE_BONUS.get(self.warframe_key)
        if fn:
            mult += fn(self.ability_flags)
        return mult


# ── EnemyEntity ────────────────────────────────────────────────────────────────

class EnemyEntity(Entity):
    """AI-controlled enemy. Selects actions based on behavior and HP thresholds."""

    def __init__(self, enemy_key: str, enemy_data: dict) -> None:
        super().__init__(
            name=enemy_data["name"],
            hp=enemy_data["hp"],
            shields=enemy_data.get("shields", 0),
            armor=enemy_data.get("armor", 0),
            energy=100,
            max_energy=100,
        )
        self.enemy_key  = enemy_key
        self.enemy_data = enemy_data
        self.faction    = enemy_data["faction"]
        self.behavior   = enemy_data["behavior"]
        self.icon       = enemy_data.get("icon", "<:damage:1499651176419950622>")
        self.xp_reward  = enemy_data.get("xp_reward", 30)
        self._abilities = enemy_data["abilities"]
        self.drops_rolled: bool = False

    def outgoing_damage_mult(self) -> float:
        mult = 1.0
        if self.has_status(StatusType.COLD):
            mult -= 0.30
        if self.has_status(StatusType.PUNCTURE):
            mult -= 0.30
        return max(0.1, mult)

    def choose_action(self) -> dict:
        for ab in self._abilities:
            cond = ab.get("condition")
            if cond == "shields_low" and self.shields < self.max_shields * 0.5:
                return ab

        attacks = [ab for ab in self._abilities if ab.get("damage", 0) > 0]
        if not attacks:
            return self._abilities[0]

        if self.behavior == "aggressive":
            if len(attacks) > 1 and random.random() < 0.35:
                return attacks[1]
            return attacks[0]

        if self.behavior == "melee":
            return max(attacks, key=lambda a: a.get("damage", 0))

        import logging
        logging.getLogger(__name__).warning(
            "Unknown behavior %r on %s — falling back to first attack",
            self.behavior, self.name,
        )
        return attacks[0]
