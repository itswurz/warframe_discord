# combat/entities.py
# ─────────────────────────────────────────────────────────────────────────────
# Three classes:
#   Entity         — shared HP / shields / armor / energy / status logic
#   WarframeEntity — player-controlled; tracks combo_gauge, passive flags
#   EnemyEntity    — AI-controlled; faction, behavior, ability selection
#
# Damage model (wiki-accurate, TB-adapted):
#   armor_reduction = armor / (armor + 300)
#   effective_damage = raw × (1 − armor_reduction)
#   Slash Bleed, Toxin, Gas, and True damage bypass armor entirely.
#   Toxin and Gas also bypass shields.
#   Magnetized doubles ALL incoming damage.
#   Viral amplifies HP damage: ×1.75 first stack, +0.25× per additional (5× max).
#   Magnetic amplifies shield damage: ×2.0 first stack, +0.25× per additional (10× max).
#   Shields absorb damage before HP (except bypass types above).
#   Heat — magnitude accumulates across stacks (up to 10×); ≥3 stacks = Panic.
#   Cold — slow% scales with stacks (−50% first, −5% each extra); 10 stacks = Frozen.
#   Puncture — damage reduction scales (−40% first, −10% each extra; 5× max).
#   Corrosive — TEMPORARY armor strip (restores on expiry); first −26%, each −6%.
#   Electric — stuns target on first application; arcs handled in session.
#   Blast — plants charge (5× max); detonates at max stacks for AoE.
#   Radiation — confusion; each extra stack extends duration +1 turn.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import random
from typing import Optional
from combat.status import (
    StatusEffect, StatusType,
    make_slash_bleed, make_stunned, make_knockdown,
    dmg_icon, HEAT_PANIC_THRESHOLD, COLD_FROZEN_THRESHOLD,
    BLAST_DETONATE_THRESHOLD,
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

        # Tracks armor stripped by Corrosive; restored on Corrosive expiry
        self.corrosive_stripped: int = 0

        # Set True by Magnetic proc when shields are fully stripped this hit;
        # session end phase reads + clears this to trigger bonus Electric arc.
        self.magnetic_shield_stripped: bool = False

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

    def is_frozen(self) -> bool:
        """True when Cold has reached 10 stacks (Frozen solid — cannot act)."""
        cold = self.get_status(StatusType.COLD)
        return bool(cold and cold.stacks >= COLD_FROZEN_THRESHOLD)

    def is_panicked(self) -> bool:
        """50% chance to skip action when Heat has ≥3 stacks (Panic)."""
        heat = self.get_status(StatusType.HEAT)
        if heat and heat.stacks >= HEAT_PANIC_THRESHOLD:
            return random.random() < 0.50
        return False

    def can_act(self) -> bool:
        if self.is_frozen():
            return False
        blocking = (
            StatusType.KNOCKDOWN,
            StatusType.BLIND,
            StatusType.STUNNED,
            StatusType.MAGNETIZED,
        )
        return self.is_alive and not any(self.has_status(b) for b in blocking)

    def is_confused(self) -> bool:
        rad = self.get_status(StatusType.RADIATION)
        return bool(rad) and random.random() < 0.50

    # ── Effective armor ────────────────────────────────────────────────────────

    def effective_armor(self) -> int:
        return max(0, self.armor)

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

        # Armor mitigation (bypassed by true/slash/toxin/gas)
        if damage_type not in ("true", "slash", "toxin", "gas"):
            raw *= self._armor_mult(damage_type)

        # Magnetized doubles all incoming damage
        if self.has_status(StatusType.MAGNETIZED):
            raw *= 2.0

        dmg = max(1, int(raw))
        toxin_bypass = damage_type in ("toxin", "gas")

        # ── Shield layer ──────────────────────────────────────────────────────
        if not bypass_shields and not toxin_bypass and self.shields > 0:
            mag = self.get_status(StatusType.MAGNETIC)
            if mag:
                # Magnetic amplifies shield damage
                shield_mult = 2.0 + (mag.stacks - 1) * 0.25
                shield_dmg  = int(dmg * shield_mult)
                if shield_dmg <= self.shields:
                    self.shields -= shield_dmg
                    return 0
                # Shield fully stripped — remaining HP damage (unamplifed overflow)
                self.shields = 0
                self.magnetic_shield_stripped = True
                # overflow bleeds through at original scale
                overflow = dmg - max(1, int(self.shields / shield_mult)) if shield_mult > 1 else 1
                dmg = max(1, overflow)
            else:
                if dmg <= self.shields:
                    self.shields -= dmg
                    return 0
                dmg -= self.shields
                self.shields = 0

        # ── HP layer ──────────────────────────────────────────────────────────
        # Viral amplifies HP damage taken
        viral = self.get_status(StatusType.VIRAL)
        if viral:
            viral_mult = 1.75 + (viral.stacks - 1) * 0.25   # 1.75 → 2.75 at stacks 1–5
            dmg = max(1, int(dmg * viral_mult))

        self.hp = max(0, self.hp - dmg)
        return dmg

    def heal_hp(self, amount: int) -> int:
        gained = min(amount, self.max_hp - self.hp)
        self.hp += gained
        return gained

    def restore_shields(self, amount: int) -> int:
        # Shields cannot regenerate while Magnetic or Cold-Frozen is active
        if self.has_status(StatusType.MAGNETIC) or self.is_frozen():
            return 0
        gained = min(amount, self.max_shields - self.shields)
        self.shields += gained
        return gained

    # ── Status application ────────────────────────────────────────────────────

    def apply_status(self, effect: StatusEffect) -> bool:
        """
        Apply a status effect, handling stacking per wiki rules.
        Returns True if a Blast detonation threshold was reached (5 stacks).
        """
        stype = effect.status_type

        # ── SLASH: unlimited independent bleeds (cap at 10 concurrent) ────────
        if stype == StatusType.SLASH_BLEED:
            current = sum(1 for s in self.statuses if s.status_type == StatusType.SLASH_BLEED)
            if current < 10:
                self.statuses.append(effect)
            return False

        # ── PUNCTURE: stacks 5×; −40% first, −10% each extra ─────────────────
        if stype == StatusType.PUNCTURE:
            existing = self.get_status(StatusType.PUNCTURE)
            if existing:
                if existing.stacks < 5:
                    existing.stacks += 1
                    existing.magnitude = 0.40 + (existing.stacks - 1) * 0.10
                    existing.data["crit_bonus"] = existing.stacks * 0.05
                    existing.duration = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── IMPACT: stacks 5×; +8% Mercy threshold per stack ─────────────────
        if stype == StatusType.IMPACT:
            existing = self.get_status(StatusType.IMPACT)
            if existing:
                if existing.stacks < 5:
                    existing.stacks += 1
                    existing.magnitude = existing.stacks * 0.08
                    existing.duration = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── HEAT: stacks 10×; magnitudes accumulate ───────────────────────────
        if stype == StatusType.HEAT:
            existing = self.get_status(StatusType.HEAT)
            if existing:
                if existing.stacks < 10:
                    existing.stacks   += 1
                    existing.magnitude += effect.magnitude
                    existing.duration  = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── COLD: stacks 10×; slow% scales per stack ─────────────────────────
        if stype == StatusType.COLD:
            existing = self.get_status(StatusType.COLD)
            if existing:
                if existing.stacks < COLD_FROZEN_THRESHOLD:
                    existing.stacks   += 1
                    existing.magnitude = 0.50 + (existing.stacks - 1) * 0.05
                    existing.duration  = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── ELECTRIC: stacks 10×; stun on first apply ────────────────────────
        if stype == StatusType.ELECTRIC:
            existing = self.get_status(StatusType.ELECTRIC)
            if existing:
                if existing.stacks < 10:
                    existing.stacks   += 1
                    existing.magnitude = existing.magnitude + effect.magnitude * 0.5
                    existing.duration  = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
                # First application stuns target for 1 turn
                if not self.has_status(StatusType.STUNNED):
                    self.statuses.append(make_stunned(1, effect.source))
            return False

        # ── TOXIN: stacks 10×; magnitudes accumulate ─────────────────────────
        if stype == StatusType.TOXIN:
            existing = self.get_status(StatusType.TOXIN)
            if existing:
                if existing.stacks < 10:
                    existing.stacks   += 1
                    existing.magnitude += effect.magnitude
                    existing.duration  = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── BLAST: stacks 5×; detonates at max ───────────────────────────────
        if stype == StatusType.BLAST:
            existing = self.get_status(StatusType.BLAST)
            if existing:
                if existing.stacks < BLAST_DETONATE_THRESHOLD:
                    existing.stacks   += 1
                    existing.magnitude += effect.magnitude
                    existing.duration  = max(existing.duration, effect.duration)
                    if existing.stacks >= BLAST_DETONATE_THRESHOLD:
                        return True  # signal: detonate!
            else:
                self.statuses.append(effect)
            return False

        # ── CORROSIVE: stacks 10×; TEMPORARY; varying strip amounts ──────────
        if stype == StatusType.CORROSIVE:
            existing = self.get_status(StatusType.CORROSIVE)
            if existing:
                if existing.stacks < 10:
                    existing.stacks += 1
                    strip = int(self.base_armor * 0.06)
                    self.armor = max(0, self.armor - strip)
                    self.corrosive_stripped += strip
                    existing.duration = max(existing.duration, effect.duration)
            else:
                strip = int(self.base_armor * 0.26)
                self.armor = max(0, self.armor - strip)
                self.corrosive_stripped += strip
                self.statuses.append(effect)
            return False

        # ── GAS: stacks 10×; magnitudes accumulate ───────────────────────────
        if stype == StatusType.GAS:
            existing = self.get_status(StatusType.GAS)
            if existing:
                if existing.stacks < 10:
                    existing.stacks   += 1
                    existing.magnitude += effect.magnitude * 0.5
                    existing.duration  = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── MAGNETIC: stacks 10×; nullifies shield regen (handled in restore) ─
        if stype == StatusType.MAGNETIC:
            existing = self.get_status(StatusType.MAGNETIC)
            if existing:
                if existing.stacks < 10:
                    existing.stacks += 1
                    existing.duration = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── RADIATION: stacks 5×; each stack extends duration +1 turn ─────────
        if stype == StatusType.RADIATION:
            existing = self.get_status(StatusType.RADIATION)
            if existing:
                if existing.stacks < 5:
                    existing.stacks   += 1
                    existing.duration += 1
            else:
                self.statuses.append(effect)
            return False

        # ── VIRAL: stacks 5×; multiplier scales per stack ────────────────────
        if stype == StatusType.VIRAL:
            existing = self.get_status(StatusType.VIRAL)
            if existing:
                if existing.stacks < 5:
                    existing.stacks   += 1
                    existing.magnitude = 1.75 + (existing.stacks - 1) * 0.25
                    existing.duration  = max(existing.duration, effect.duration)
            else:
                self.statuses.append(effect)
            return False

        # ── All other statuses: refresh if new duration is longer ─────────────
        for ex in self.statuses:
            if ex.status_type == stype:
                if effect.duration > ex.duration:
                    ex.duration  = effect.duration
                    ex.magnitude = effect.magnitude
                return False
        self.statuses.append(effect)
        return False

    def remove_status(self, stype: StatusType) -> None:
        self.statuses = [s for s in self.statuses if s.status_type != stype]

    def tick_statuses(self) -> list[str]:
        """
        Called during End Phase. Process all DoT / lingering effects,
        decrement durations, purge expired. Returns log lines.
        """
        messages: list[str] = []

        for s in list(self.statuses):
            stype = s.status_type

            # ── Slash Bleed — true damage, bypasses armor & shields ────────
            if stype == StatusType.SLASH_BLEED:
                dmg = max(1, int(s.magnitude))
                self.hp = max(0, self.hp - dmg)
                messages.append(
                    f"{s.icon()} **{self.name}** bleeds for "
                    f"**{dmg}** {dmg_icon('true')} True dmg! "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Heat — fire DoT ───────────────────────────────────────────
            elif stype == StatusType.HEAT:
                dmg = max(1, int(s.magnitude))
                self.hp = max(0, self.hp - dmg)
                stack_note = f" ×{s.stacks}" if s.stacks > 1 else ""
                panic_note = " 🔥*Panic!*" if s.stacks >= HEAT_PANIC_THRESHOLD else ""
                messages.append(
                    f"{s.icon()} **{self.name}** burns for **{dmg}** "
                    f"{dmg_icon('heat')} Heat dmg!{stack_note}{panic_note} "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Toxin — DoT that bypasses shields ─────────────────────────
            elif stype == StatusType.TOXIN:
                dmg = max(1, int(s.magnitude))
                self.hp = max(0, self.hp - dmg)
                stack_note = f" ×{s.stacks}" if s.stacks > 1 else ""
                messages.append(
                    f"{s.icon()} **{self.name}** poisoned for **{dmg}** "
                    f"{dmg_icon('toxin')} Toxin dmg!{stack_note} "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Gas — AoE Toxin cloud (AoE portion handled in session) ────
            elif stype == StatusType.GAS:
                dmg = max(1, int(s.magnitude))
                self.hp = max(0, self.hp - dmg)
                stack_note = f" ×{s.stacks}" if s.stacks > 1 else ""
                messages.append(
                    f"{s.icon()} **{self.name}** chokes on Gas cloud for **{dmg}** "
                    f"{dmg_icon('toxin')} Toxin dmg!{stack_note} "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Blast — delayed detonation tick ──────────────────────────
            elif stype == StatusType.BLAST:
                tick_dmg = max(1, int(s.magnitude * 0.30))
                self.hp = max(0, self.hp - tick_dmg)
                stack_note = f" ×{s.stacks}" if s.stacks > 1 else ""
                messages.append(
                    f"{s.icon()} **{self.name}**'s charge detonates for **{tick_dmg}** "
                    f"{dmg_icon('blast')} Blast dmg!{stack_note} "
                    f"(HP: {self.hp}/{self.max_hp})"
                )

            # ── Corrosive — no tick damage; armor already stripped ─────────
            # Handled on expiry below

            # Tesla Coil, Polarize Shard, Electric arcs, Gas AoE
            # are resolved at session level (need access to other entities)

        # ── Expiry callbacks ──────────────────────────────────────────────────
        new_statuses: list[StatusEffect] = []
        for s in self.statuses:
            if not s.tick():
                if s.status_type == StatusType.CORROSIVE and self.corrosive_stripped > 0:
                    self.armor = min(self.base_armor, self.armor + self.corrosive_stripped)
                    self.corrosive_stripped = 0
                    messages.append(
                        f"{s.icon()} **{self.name}**'s armor recovers — Corrosion faded! "
                        f"(Armor: {self.armor})"
                    )
                elif s.status_type == StatusType.COLD and s.stacks >= COLD_FROZEN_THRESHOLD:
                    messages.append(f"{s.icon()} **{self.name}** thaws!")
                elif s.status_type == StatusType.BLAST and s.stacks > 0:
                    messages.append(
                        f"{s.icon()} **{self.name}**'s charge fizzled out "
                        f"({s.stacks} stack{'s' if s.stacks > 1 else ''} wasted)."
                    )
            else:
                new_statuses.append(s)
        self.statuses = new_statuses
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

        self.mod_stats: dict = mod_stats or {}
        self.warframe_key   = warframe_key
        self.warframe_data  = warframe_data
        self.combo_gauge    = 0
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
        self.is_shielded: bool  = False

    def take_damage(
        self,
        amount:         float,
        damage_type:    str  = "true",
        bypass_shields: bool = False,
    ) -> int:
        """Override — absorbs all damage while Sphere Shield is active."""
        if self.is_shielded:
            return 0
        return super().take_damage(amount, damage_type, bypass_shields)

    def outgoing_damage_mult(self) -> float:
        """
        Stack-aware outgoing damage multiplier.
        Cold: −50% first stack, −5% each additional (max −90% at stack 10).
        Puncture: −40% first stack, −10% each additional (max −80% at stack 5).
        Both stack cumulatively (e.g. Cold ×3 + Puncture ×2 = −65% −50% = ×0.15 floor 0.05).
        """
        mult = 1.0

        cold = self.get_status(StatusType.COLD)
        if cold:
            slow = min(0.90, 0.50 + (cold.stacks - 1) * 0.05)
            mult -= slow

        punct = self.get_status(StatusType.PUNCTURE)
        if punct:
            weaken = min(0.80, 0.40 + (punct.stacks - 1) * 0.10)
            mult -= weaken

        return max(0.05, mult)

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

        if self.behavior == "boss":
            # Weighted random selection across all available attacks
            total = sum(ab.get("chance", 0.5) for ab in attacks)
            r = random.random() * total
            cumulative = 0.0
            for ab in attacks:
                cumulative += ab.get("chance", 0.5)
                if r <= cumulative:
                    return ab
            return attacks[-1]

        import logging
        logging.getLogger(__name__).warning(
            "Unknown behavior %r on %s — falling back to first attack",
            self.behavior, self.name,
        )
        return attacks[0]
