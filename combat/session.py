# combat/session.py
# ─────────────────────────────────────────────────────────────────────────────
# CombatSession — single authoritative game state for one encounter.
#
# Weapon slots (all fully dynamic — read from WEAPON_STATS):
#   self.primary_weapon_name    — chosen by player (MK1-Braton / Paris / …)
#   self.melee_weapon_name      — default "Skana"; expandable
#   self.secondary_weapon_name  — default "Lato"; expandable
#
# Persistence integration:
#   self.mission_loot            — aggregated drop dicts (all enemies)
#   self.mission_damage_dealt    — running total of player damage this mission
#   self.mission_credits_earned  — credits to award on completion
#   self.highest_combo_reached   — peak combo_gauge value seen this mission
#   self.loot_posted             — True after the post-mission embed + profile
#                                   commit have both fired (guards double-run)
#
# Drop collection:
#   _collect_drops() is called after every kill and after the end phase.
#   It is guarded by enemy.drops_rolled so it never double-rolls.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import random
from typing import Optional

from combat.entities import WarframeEntity, EnemyEntity
from combat.status import (
    StatusType, dmg_icon,
    make_knockdown, make_slash_bleed,
    make_puncture, make_impact, make_heat,
    make_cold, make_electric, make_toxin,
    make_blast, make_radiation, make_magnetic_proc,
    make_viral, make_corrosive, make_gas,
)
from data.enemies import ENEMIES, INTRO_ENCOUNTER

# ── Module-level session registry ─────────────────────────────────────────────
ACTIVE_SESSIONS: dict[int, "CombatSession"] = {}

MAX_ACTIONS  = 2
ENERGY_REGEN = 25

# ── Credits awarded per mission outcome ───────────────────────────────────────
CREDITS_VICTORY = 150
CREDITS_DEFEAT  = 40

# ── Emoji constants ───────────────────────────────────────────────────────────
_KNOCKDOWN  = "<:stunned:1499671616479563826>"
_STUNNED    = "<:stunned:1499671616479563826>"
_DOWN       = "<:down:1499663521414119535>"
_SHIELD     = "<:wf_shield:1499636531755745280>"
_LOTUS      = "<:wf_lotus:1499651243101126816>"
_ENERGY     = "<a:energy_orb:1499636329842212964>"
_ELEC       = "<:electricity:1499596184958795917>"
_IMPACT     = "<:impact:1499636596633374780>"
_SLASH_ICON = "<:slash_effect:1499584690859020459>"
_MAG        = "<:magnetic:1499594471770427472>"
_BLAST_ICO  = "<:blast:1499594820102914210>"
_SPEED      = "<:speed:1499596301984071832>"
_EXALTED    = "<:exalted_blade:1499575259526074468>"
_MAGNETIZE  = "<:magnetize:1499595149091668103>"
_POLARIZE   = "<:polarize:1499595238786994246>"
_EL_SHIELD  = "<:electric_shield:1499596339674349658>"
_DISCHARGE  = "<:discharge:1499596381508075550>"
_PUNCT      = "<:puncture:1499594734421803060>"
_STAT_NEG   = "<:stat_negative:1499636840494399638>"


class CombatState:
    PLAYER_TURN = "player_turn"
    ENEMY_TURN  = "enemy_turn"
    VICTORY     = "victory"
    DEFEAT      = "defeat"


class CombatSession:

    def __init__(
        self,
        warframe_key:      str,
        warframe_data:     dict,
        user_id:           int,
        primary_weapon:    str  = "MK1-Braton",
        melee_weapon:      str  = "Skana",
        secondary_weapon:  str  = "Lato",
        profile:           dict | None = None,
    ) -> None:
        self.user_id = user_id

        # ── Resolve mod bonuses from equipped mods ────────────────────────────
        # If a full player profile is supplied, look up the active warframe
        # instance and compute the final stats (HP/shields/armor/energy) after
        # all equipped mods have been applied.  Falls back to base stats when
        # no profile is provided (e.g. tests, legacy !combat command).
        mod_stats: dict | None = None
        if profile:
            try:
                from utils.mods_ui import get_active_stat_bonuses, get_wf_instance
                from data.persistence import get_active_warframe_instance
                wf_inst = get_active_warframe_instance(profile)
                # Also try matching by warframe_key if is_active flag is missing
                if wf_inst is None:
                    for w in profile.get("warframe_roster", []):
                        if w.get("warframe_key") == warframe_key:
                            wf_inst = w
                            break
                if wf_inst is not None:
                    mod_stats = get_active_stat_bonuses(profile, wf_inst)
            except Exception:
                import traceback
                traceback.print_exc()
                mod_stats = None

        self.player  = WarframeEntity(warframe_key, warframe_data, mod_stats=mod_stats)
        self.enemies = self._spawn_enemies()
        self.turn    = 1
        self.state   = CombatState.PLAYER_TURN

        self.actions_used  = 0
        self.bonus_actions = 0

        # ── Weapon slots — all dynamic ────────────────────────────────────────
        self.primary_weapon_name:   str = primary_weapon
        self.melee_weapon_name:     str = melee_weapon
        self.secondary_weapon_name: str = secondary_weapon

        # ── Drop / loot tracking ──────────────────────────────────────────────
        self.mission_loot: list[dict] = []

        # ── Mission accounting ────────────────────────────────────────────────
        self.mission_damage_dealt:   int  = 0
        self.mission_credits_earned: int  = 0
        self.highest_combo_reached:  int  = 0

        # Guards the post-mission commit + loot embed so they fire exactly once
        self.loot_posted: bool = False

        # ── Session-level field effect flags ──────────────────────────────────
        self.player_untargetable:         bool  = False
        self.electric_shield_active:      bool  = False
        self.electric_shield_turns:       int   = 0
        self.electric_shield_stacks:      int   = 0
        self.electric_shield_electrified: bool  = False
        self.magnetize_target: Optional[EnemyEntity] = None
        self.magnetize_turns:             int   = 0
        self.polarize_shards_absorbed:    bool  = False

        self._turn_drains: dict[str, tuple[WarframeEntity, float]] = {}

        # ── Pull weapon display names for the opening log ─────────────────────
        from combat.weapons import WEAPON_STATS
        _pw = WEAPON_STATS.get(self.primary_weapon_name, {})
        _mw = WEAPON_STATS.get(self.melee_weapon_name,   {})
        _sw = WEAPON_STATS.get(self.secondary_weapon_name, {})
        _pe = _pw.get("emoji", "")
        _me = _mw.get("emoji", "")
        _se = _sw.get("emoji", "")

        self.log: list[str] = [
            f"━━━ Turn {self.turn} — **Your Turn** ━━━",
            f"{_ENERGY} Energy: {self.player.energy}/{self.player.max_energy}",
            (
                f"{_LOTUS} Loadout: "
                f"{_pe} **{self.primary_weapon_name}**  ·  "
                f"{_se} **{self.secondary_weapon_name}**  ·  "
                f"{_me} **{self.melee_weapon_name}**"
            ),
        ]

        # ── Announce active mod bonuses so the player can see them take effect ─
        if mod_stats:
            bonus_parts = []
            if mod_stats.get("ability_efficiency_bonus"):
                bonus_parts.append(
                    f"-{mod_stats['ability_efficiency_bonus']}% ability cost"
                )
            if mod_stats.get("puncture_resist_bonus"):
                bonus_parts.append(
                    f"+{mod_stats['puncture_resist_bonus']}% Puncture resist"
                )
            if mod_stats.get("electricity_store_bonus"):
                bonus_parts.append(
                    f"+{mod_stats['electricity_store_bonus']}% arc store"
                )
            self.log.append(
                f"{_LOTUS} Mods active — "
                f"<a:health:1499636458309423215> **{self.player.max_hp}** HP  ·  "
                f"<:wf_shield:1499636531755745280> **{self.player.max_shields}** Shields  ·  "
                f"<:damage_reduction:1499651603945226260> **{self.player.armor}** Armor  ·  "
                f"<a:energy_orb:1499636329842212964> **{self.player.max_energy}** Energy"
                + (f"  ·  {', '.join(bonus_parts)}" if bonus_parts else "")
            )

        self.log.append(
            f"{_LOTUS} The Origin System waits for no one. Choose your action, Tenno."
        )

    # ── Spawn ──────────────────────────────────────────────────────────────────

    def _spawn_enemies(self) -> list[EnemyEntity]:
        return [EnemyEntity(k, ENEMIES[k]) for k in INTRO_ENCOUNTER]

    # ── Queries ────────────────────────────────────────────────────────────────

    def living_enemies(self) -> list[EnemyEntity]:
        return [e for e in self.enemies if e.is_alive]

    def get_primary_target(self) -> Optional[EnemyEntity]:
        living = self.living_enemies()
        return living[0] if living else None

    @property
    def actions_remaining(self) -> int:
        return max(0, MAX_ACTIONS + self.bonus_actions - self.actions_used)

    @property
    def is_player_turn(self) -> bool:
        return self.state == CombatState.PLAYER_TURN

    @property
    def is_over(self) -> bool:
        return self.state in (CombatState.VICTORY, CombatState.DEFEAT)

    # ── Accounting helper ──────────────────────────────────────────────────────

    def _record_damage(self, amount: int) -> None:
        self.mission_damage_dealt += max(0, amount)
        if self.player.combo_gauge > self.highest_combo_reached:
            self.highest_combo_reached = self.player.combo_gauge

    # ── Turn drain API ─────────────────────────────────────────────────────────

    def register_turn_drain(self, key: str, entity: WarframeEntity, amount: float) -> None:
        self._turn_drains[key] = (entity, amount)

    def unregister_turn_drain(self, key: str) -> None:
        self._turn_drains.pop(key, None)

    # ── Drop collection ────────────────────────────────────────────────────────

    def _collect_drops(self) -> None:
        from data.drops import roll_drops

        for enemy in self.enemies:
            if enemy.is_alive or enemy.drops_rolled:
                continue

            enemy.drops_rolled = True
            drops = roll_drops(enemy.enemy_key)

            if not drops:
                continue

            self.log.append(f"{enemy.icon} **{enemy.name}** drops loot!")

            for drop in drops:
                self.mission_loot.append(drop)
                emoji = drop["emoji"]
                name  = drop["name"]
                amt   = drop["amount"]
                dtype = drop["type"]

                if dtype == "mod":
                    rarity = drop["rarity"].capitalize()
                    self.log.append(f"  {emoji} **{name}** *(Mod — {rarity})*")
                elif dtype == "endo":
                    self.log.append(f"  {emoji} **{amt} Endo**")
                else:
                    amt_str = f" ×{amt}" if isinstance(amt, int) and amt > 1 else ""
                    self.log.append(f"  {emoji} **{name}**{amt_str}")

    # ── Player action entry point ──────────────────────────────────────────────

    def can_use_ability(self, energy_cost: int) -> tuple[bool, str]:
        if self.state != CombatState.PLAYER_TURN:
            return False, "It is not your turn, Tenno."
        if self.actions_remaining <= 0:
            return False, "No actions remaining. End your turn."
        if self.player.energy < energy_cost:
            return False, (
                f"Insufficient Energy. "
                f"Need **{energy_cost}**, have **{self.player.energy}**."
            )
        if not self.player.is_alive:
            return False, "You have been defeated."
        return True, ""

    def player_action(self, ability_index: Optional[int], hold: bool = False) -> list[str]:
        from combat.abilities import use_ability, basic_attack, ABILITY_COSTS

        if ability_index is None:
            ok, reason = self.can_use_ability(0)
            if not ok:
                return [reason]
            result = basic_attack(self, self.player)
        else:
            from combat.abilities import (
                use_ability, basic_attack, ABILITY_COSTS,
                DEFAULT_ABILITY_COSTS, TOGGLE_ABILITY_INDEX, TOGGLE_FLAG_KEY,
            )
            costs = ABILITY_COSTS.get(self.player.warframe_key, DEFAULT_ABILITY_COSTS)
            cost  = costs[ability_index] if ability_index < len(costs) else 0

            toggle_idx = TOGGLE_ABILITY_INDEX.get(self.player.warframe_key)
            toggle_key = TOGGLE_FLAG_KEY.get(self.player.warframe_key)
            if (
                toggle_idx is not None
                and ability_index == toggle_idx
                and toggle_key is not None
                and self.player.ability_flags.get(toggle_key)
            ):
                cost = 0

            ok, reason = self.can_use_ability(cost)
            if not ok:
                return [reason]

            result = use_ability(self, self.player, ability_index, hold)

        self.player.energy = max(0, self.player.energy - result.used_energy)
        self.actions_used += 1

        self._record_damage(result.dealt_damage)

        from combat.abilities import STATIC_CHARGE_WARFRAMES
        if ability_index is not None and self.player.warframe_key in STATIC_CHARGE_WARFRAMES:
            charges = self.player.ability_flags.get("static_charges", 0)
            if charges < 5:
                self.player.ability_flags["static_charges"] = charges + 1
                result.log.append(
                    f"{_ELEC} Static Discharge: "
                    f"**{self.player.ability_flags['static_charges']}/5** charges built."
                )

        self.log.extend(result.log)
        self._collect_drops()
        self._check_victory()
        return self.log[-12:]

    # ── Melee weapon attack ────────────────────────────────────────────────────

    def player_melee(self) -> list[str]:
        from combat.abilities import melee_attack

        ok, reason = self.can_use_ability(0)
        if not ok:
            return [reason]

        result = melee_attack(self, self.player)
        self.player.energy = max(0, self.player.energy - result.used_energy)
        self.actions_used += 1
        self._record_damage(result.dealt_damage)

        self.log.extend(result.log)
        self._collect_drops()
        self._check_victory()
        return self.log[-12:]

    # ── Secondary weapon attack ────────────────────────────────────────────────

    def player_secondary(self) -> list[str]:
        from combat.abilities import secondary_attack

        ok, reason = self.can_use_ability(0)
        if not ok:
            return [reason]

        result = secondary_attack(self, self.player)
        self.player.energy = max(0, self.player.energy - result.used_energy)
        self.actions_used += 1
        self._record_damage(result.dealt_damage)

        self.log.extend(result.log)
        self._collect_drops()
        self._check_victory()
        return self.log[-12:]

    def end_player_turn(self) -> list[str]:
        self.log.append(f"━━━ Turn {self.turn} — **Enemy Phase** ━━━")
        self.state = CombatState.ENEMY_TURN

        self.player_untargetable = False
        self.bonus_actions       = 0

        self._run_enemy_turn()
        self._collect_drops()
        self._run_end_phase()

        if not self.is_over:
            self._start_player_turn()

        return self.log[-14:]

    # ── Enemy AI ───────────────────────────────────────────────────────────────

    def _run_enemy_turn(self) -> None:
        for enemy in self.living_enemies():

            # Hard CC blocks action
            if not enemy.can_act():
                cc_status = next(
                    (s for s in enemy.statuses
                     if s.status_type in (
                         StatusType.KNOCKDOWN, StatusType.STUNNED,
                         StatusType.BLIND, StatusType.MAGNETIZED,
                     )),
                    None,
                )
                cc_icon = cc_status.icon() if cc_status else _STUNNED
                cc_name = cc_status.name.lower() if cc_status else "incapacitated"
                self.log.append(f"{cc_icon} **{enemy.name}** is {cc_name} — skips turn.")
                continue

            action = enemy.choose_action()

            # Radiation confusion
            if enemy.is_confused():
                confused_target = random.choice(
                    [e for e in self.living_enemies() if e is not enemy] or [enemy]
                )
                self.log.append(
                    f"{dmg_icon('radiation')} **{enemy.name}** is Irradiated and attacks "
                    f"**{confused_target.name}** by mistake! ({action['name']})"
                )
                raw_dmg  = action.get("damage", 0)
                dtype    = action.get("damage_type", "impact")
                dmg_mult = enemy.outgoing_damage_mult()
                if raw_dmg > 0:
                    hit = max(1, int(raw_dmg * dmg_mult))
                    confused_target.hp = max(0, confused_target.hp - hit)
                    self.log.append(
                        f"  {dmg_icon(dtype)} **{confused_target.name}** takes "
                        f"**{hit}** {dmg_icon(dtype)} {dtype} dmg from friendly fire! "
                        f"(HP: {confused_target.hp}/{confused_target.max_hp})"
                    )
                    if not confused_target.is_alive:
                        self.log.append(
                            f"  {_DOWN} **{confused_target.name}** defeated by friendly fire!"
                        )
                continue

            self.log.append(f"{enemy.icon} **{enemy.name}** uses **{action['name']}**!")

            # Self-buff / heal
            if action.get("target") == "self":
                if action.get("effect") == "self_shield_restore":
                    heal = action.get("heal_amount", 60)
                    restored = enemy.restore_shields(heal)
                    self.log.append(
                        f"  {_SHIELD} **{enemy.name}** restores **{restored}** Shields! "
                        f"({enemy.shields}/{enemy.max_shields})"
                    )
                continue

            # Ranged attack — check Electric Shield
            if action.get("target") == "front" and self.electric_shield_active:
                if self.electric_shield_electrified:
                    zap = 65
                    enemy.take_damage(zap, "electricity")
                    self.log.append(
                        f"  {_ELEC} Electrified shield zaps **{enemy.name}** for "
                        f"**{zap}** {_ELEC} Electricity!"
                    )
                    if not enemy.is_alive:
                        self.log.append(f"  {_DOWN} **{enemy.name}** defeated by the shield!")
                        continue
                self.log.append(
                    f"  {_EL_SHIELD} Electric Shield blocks **{enemy.name}**'s ranged attack!"
                )
                continue

            # Player untargetable
            if self.player_untargetable:
                self.log.append(
                    f"  {_SPEED} **{self.player.name}** is untargetable — "
                    f"**{enemy.name}**'s attack misses!"
                )
                continue

            # Mag defensive Magnetize absorption
            if self.player.magnetize_absorb:
                stored = max(1, int(action.get("damage", 0) * self.player._armor_mult()))
                self.player.magnetize_stored += stored
                self.log.append(
                    f"  {_MAGNETIZE} **{enemy.name}**'s attack absorbed! "
                    f"({stored} stored, total {self.player.magnetize_stored})"
                )
                continue

            # Deal damage to player
            raw_dmg  = action.get("damage", 0)
            dtype    = action.get("damage_type", "impact")
            dmg_mult = enemy.outgoing_damage_mult()
            icon     = dmg_icon(dtype)

            if dmg_mult < 1.0:
                debuff_icon = (
                    dmg_icon("cold") if enemy.has_status(StatusType.COLD)
                    else dmg_icon("puncture")
                )
                self.log.append(
                    f"  {debuff_icon} **{enemy.name}** is debuffed! "
                    f"(×{dmg_mult:.2f} damage output)"
                )

            if raw_dmg > 0:
                effective = max(1, int(raw_dmg * dmg_mult))
                hp_dmg = self.player.take_damage(effective, dtype)
                if hp_dmg > 0:
                    self.log.append(
                        f"  {icon} **{self.player.name}** takes **{effective}** {icon} {dtype} dmg! "
                        f"(HP: {self.player.hp}/{self.player.max_hp})"
                    )
                else:
                    self.log.append(
                        f"  {_SHIELD} Shields absorb **{effective}** {icon} {dtype}! "
                        f"(Shields: {self.player.shields}/{self.player.max_shields})"
                    )

            # Enemy status procs on player
            effect = action.get("effect")
            chance = action.get("chance", 0.5)
            if effect and random.random() < chance:
                if effect == "knockdown":
                    self.player.apply_status(make_knockdown(source=enemy.name))
                    self.log.append(
                        f"  {_KNOCKDOWN} **{self.player.name}** Knocked Down by **{enemy.name}**! "
                        f"(skips next turn)"
                    )
                elif effect == "slash_bleed":
                    mag = action.get("bleed_mag", 15)
                    self.player.apply_status(make_slash_bleed(mag, enemy.name))
                    self.log.append(
                        f"  {dmg_icon('slash')} **{self.player.name}** inflicted with Bleed by "
                        f"**{enemy.name}**! ({mag} {dmg_icon('true')} True dmg/turn × 2)"
                    )
                elif effect == "pull":
                    self.player.apply_status(make_knockdown(source=enemy.name))
                    self.log.append(
                        f"  {_KNOCKDOWN} **{enemy.name}**'s grapple pulls "
                        f"**{self.player.name}** in! (Knockdown)"
                    )
                else:
                    self.log.append(
                        f"  ⚠️ [UNHANDLED ENEMY EFFECT: {effect!r} on {enemy.name}]"
                    )

        self._check_defeat()

    # ── End phase ──────────────────────────────────────────────────────────────

    def _run_end_phase(self) -> None:
        if self.is_over:
            return

        self.log.append("━━━ **End Phase** ━━━")

        # Player status ticks
        for msg in self.player.tick_statuses():
            self.log.append(msg)

        # Release absorbed Magnetize burst
        if self.player.magnetize_absorb and self.player.magnetize_stored > 0:
            target = self.get_primary_target()
            if target:
                burst = self.player.magnetize_stored * 2
                target.take_damage(burst, "magnetic")
                self.log.append(
                    f"{_MAGNETIZE} **Magnetize Release** — stored energy bursts into "
                    f"**{target.name}** for **{burst}** {dmg_icon('magnetic')} Magnetic dmg!"
                )
                self.player.magnetize_stored = 0
        self.player.magnetize_absorb = False

        # Enemy status ticks
        living = self.living_enemies()
        for enemy in living:

            # Tesla Coil — arc to ALL other living enemies
            tesla = enemy.get_status(StatusType.TESLA_COIL)
            if tesla and enemy.is_alive:
                for other in self.living_enemies():
                    if other is not enemy:
                        arc = int(tesla.magnitude)
                        other.hp = max(0, other.hp - arc)
                        self.log.append(
                            f"  {_DISCHARGE} Tesla Coil arcs **{arc}** {_ELEC} Electricity: "
                            f"**{enemy.name}** → **{other.name}**! "
                            f"(HP: {other.hp}/{other.max_hp})"
                        )
                        if not other.is_alive:
                            self.log.append(
                                f"  {_DOWN} **{other.name}** defeated by Tesla arc!"
                            )

            # Electric proc — arc to a random OTHER enemy
            elec_proc = enemy.get_status(StatusType.ELECTRIC)
            if elec_proc and enemy.is_alive:
                others = [e for e in self.living_enemies() if e is not enemy]
                if others:
                    arc_target = random.choice(others)
                    arc        = int(elec_proc.magnitude)
                    arc_target.hp = max(0, arc_target.hp - arc)
                    self.log.append(
                        f"  {_ELEC} Electric proc arcs **{arc}** {_ELEC} from "
                        f"**{enemy.name}** → **{arc_target.name}**! "
                        f"(HP: {arc_target.hp}/{arc_target.max_hp})"
                    )

            # Gas AoE — Toxin cloud hits ALL living enemies
            gas = enemy.get_status(StatusType.GAS)
            if gas and enemy.is_alive:
                dmg = max(1, int(gas.magnitude))
                for other in self.living_enemies():
                    if other is not enemy:
                        other.hp = max(0, other.hp - dmg)
                        self.log.append(
                            f"  {dmg_icon('gas')} Gas cloud poisons **{other.name}** "
                            f"for **{dmg}** {dmg_icon('toxin')} Toxin dmg! "
                            f"(HP: {other.hp}/{other.max_hp})"
                        )

            # Polarize Shards from player — cut all enemies
            if self.player.has_status(StatusType.POLARIZE_SHARD):
                shard = self.player.get_status(StatusType.POLARIZE_SHARD)
                if shard:
                    dmg = int(shard.magnitude)
                    enemy.hp = max(0, enemy.hp - dmg)
                    self.log.append(
                        f"  {_POLARIZE} Polarize Shards cut **{enemy.name}** for **{dmg}** "
                        f"{_PUNCT} Puncture / {_SLASH_ICON} Slash! "
                        f"(HP: {enemy.hp}/{enemy.max_hp})"
                    )
                    if not enemy.is_alive:
                        self.log.append(
                            f"  {_DOWN} **{enemy.name}** shredded by the Shards!"
                        )

            # General status ticks (Bleed, Heat, Toxin, etc.)
            for msg in enemy.tick_statuses():
                self.log.append(msg)

        # Electric Shield expiry
        if self.electric_shield_active:
            self.electric_shield_turns -= 1
            if self.electric_shield_turns <= 0:
                self.electric_shield_active      = False
                self.electric_shield_electrified = False
                self.electric_shield_stacks      = 0
                self.log.append(f"{_EL_SHIELD} Electric Shield has dissipated.")

        # Magnetize expiry → explosion
        if self.magnetize_target and self.magnetize_target.is_alive:
            self.magnetize_turns -= 1
            if self.magnetize_turns <= 0:
                blast = 140
                if self.polarize_shards_absorbed:
                    blast += 90
                    self.log.append(
                        f"{_POLARIZE} Absorbed Polarize Shards amplify the explosion!"
                    )
                    self.polarize_shards_absorbed = False

                self.log.append(
                    f"{_BLAST_ICO} **Magnetize expires** — **{self.magnetize_target.name}** "
                    f"detonates for **{blast}** {_BLAST_ICO} Blast dmg!"
                )
                self.magnetize_target.take_damage(blast, "blast")
                if not self.magnetize_target.is_alive:
                    self.log.append(
                        f"  {_DOWN} **{self.magnetize_target.name}** obliterated!"
                    )
                else:
                    for enemy in self.living_enemies():
                        if enemy is not self.magnetize_target:
                            splash = int(blast * 0.5)
                            enemy.take_damage(splash, "blast")
                            self.log.append(
                                f"  {_BLAST_ICO} **{enemy.name}** caught in the explosion! "
                                f"({splash} {_BLAST_ICO} Blast, HP: {enemy.hp}/{enemy.max_hp})"
                            )
                self.magnetize_target = None

        # Per-turn energy drains (Exalted Blade and any future toggle abilities)
        for key, (entity, amount) in list(self._turn_drains.items()):
            from combat.weapons import WEAPON_STATS
            # Find the drain label dynamically from weapon data if possible
            drain_label = key.replace("_", " ").title()
            drain_emoji = _EXALTED   # default; expand per-key if needed

            drained = min(int(amount + 0.5), entity.energy)
            entity.energy = max(0, entity.energy - drained)
            self.log.append(
                f"{drain_emoji} **{drain_label}** drains **{drained}** {_ENERGY} Energy. "
                f"({entity.energy}/{entity.max_energy})"
            )
            if entity.energy == 0:
                from combat.abilities import TOGGLE_FLAG_KEY
                flag_key = TOGGLE_FLAG_KEY.get(entity.warframe_key)
                if flag_key:
                    entity.ability_flags[flag_key] = False
                self.unregister_turn_drain(key)
                self.log.append(f"{drain_emoji} **{drain_label}** — out of energy, deactivated.")

        # Collect drops for anything killed during end phase
        self._collect_drops()

        self._check_victory()
        self._check_defeat()

    # ── Player turn start ──────────────────────────────────────────────────────

    def _start_player_turn(self) -> None:
        self.turn        += 1
        self.state        = CombatState.PLAYER_TURN
        self.actions_used = 0

        gained = min(ENERGY_REGEN, self.player.max_energy - self.player.energy)
        self.player.energy += gained

        self.log.append(f"━━━ Turn {self.turn} — **Your Turn** ━━━")
        self.log.append(
            f"{_ENERGY} +{gained} Energy → **{self.player.energy}/{self.player.max_energy}**"
        )

        from combat.abilities import warframe_turn_start_log, SPEED_BUFF_WARFRAMES
        for line in warframe_turn_start_log(self, self.player):
            self.log.append(line)

        for msg in self.player.tick_statuses():
            self.log.append(msg)

        if self.player.warframe_key in SPEED_BUFF_WARFRAMES and self.player.speed_active:
            self.player.speed_turns -= 1
            if self.player.speed_turns <= 0:
                self.player.speed_active = False
                self.player.remove_status(StatusType.SPEED_BUFF)
                self.log.append(f"{_SPEED} Speed buff expired.")

    # ── Win / loss ─────────────────────────────────────────────────────────────

    def _check_victory(self) -> None:
        if not self.living_enemies() and not self.is_over:
            self.state                   = CombatState.VICTORY
            self.mission_credits_earned  = CREDITS_VICTORY
            self.log.append(
                f"{_LOTUS} **MISSION COMPLETE** — All enemies defeated, Tenno! "
                f"(**+{CREDITS_VICTORY} Credits**)"
            )

    def _check_defeat(self) -> None:
        if not self.player.is_alive and not self.is_over:
            self.state                   = CombatState.DEFEAT
            self.mission_credits_earned  = CREDITS_DEFEAT
            self.log.append(
                f"{_LOTUS} **MISSION FAILED** — Ordis mourns your loss, Operator. "
                f"(**+{CREDITS_DEFEAT} Credits** salvaged)"
            )
