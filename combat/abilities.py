# combat/abilities.py
# ─────────────────────────────────────────────────────────────────────────────
# Every player ability is a pure function:  fn(session, caster) → AbilityResult
#
# Weapon attacks
#   basic_attack()      — primary weapon (MK1-Braton or Paris — from session)
#   melee_attack()      — melee weapon (Skana / Exalted — from session)
#   secondary_attack()  — secondary weapon (Lato — from session)
#
# Adding a new weapon:
#   Add it to combat/weapons.py WEAPON_STATS.
#   All attack functions read weapon data from WEAPON_STATS via the session's
#   weapon name attributes — zero changes needed here.
#
# All log lines use dmg_icon(dtype) for the correct emoji automatically.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from combat.session import CombatSession

from combat.entities import WarframeEntity, EnemyEntity
from combat.status import (
    StatusType, dmg_icon,
    make_slash_bleed, make_puncture, make_impact,
    make_knockdown, make_blind, make_stunned,
    make_magnetized, make_tesla_coil,
    make_polarize_shard, make_speed_buff,
    make_heat, make_cold, make_electric,
    make_toxin, make_blast, make_radiation,
    make_magnetic_proc, make_viral, make_corrosive, make_gas,
)

# ── Emoji constants (from assets.txt) ─────────────────────────────────────────
_KNOCKDOWN   = "<:stunned:1499671616479563826>"
_STUNNED     = "<:stunned:1499671616479563826>"
_DOWN        = "<:down:1499663521414119535>"
_SHIELD      = "<:wf_shield:1499636531755745280>"
_LOTUS       = "<:wf_lotus:1499651243101126816>"
_COMBO       = "<:combo:1499663262520971326>"
_ENERGY      = "<a:energy_orb:1499636329842212964>"
_STAT_NEG    = "<:stat_negative:1499636840494399638>"
_STAT_POS    = "<:stat_positive:1499636780356337715>"
_ELEC        = "<:electricity:1499596184958795917>"
_IMPACT      = "<:impact:1499636596633374780>"
_SLASH_ICON  = "<:slash_effect:1499584690859020459>"
_PUNCT       = "<:puncture:1499594734421803060>"
_MAG         = "<:magnetic:1499594471770427472>"
_BLAST_ICON  = "<:blast:1499594820102914210>"
_SPEED       = "<:speed:1499596301984071832>"
_EXALTED     = "<:exalted_blade:1499575259526074468>"
_SLASH_DASH  = "<:slash_dash:1499574774429515917>"
_RADIAL_BL   = "<:radial_blind:1499574926364119050>"
_RAD_JAV     = "<:radial_javelin:1499575401343877391>"
_PULL        = "<:pull:1499595083547410643>"
_MAGNETIZE   = "<:magnetize:1499595149091668103>"
_POLARIZE    = "<:polarize:1499595238786994246>"
_CRUSH       = "<:crush:1499595185888428234>"
_SHOCK       = "<:shock:1499596261375086732>"
_EL_SHIELD   = "<:electric_shield:1499596339674349658>"
_DISCHARGE   = "<:discharge:1499596381508075550>"
_DAMAGE      = "<:damage:1499651176419950622>"
_TRUE        = "<:true:1499594920082542743>"


# ── Result container ───────────────────────────────────────────────────────────

@dataclass
class AbilityResult:
    used_energy:  int
    log:          list[str] = field(default_factory=list)
    dealt_damage: int       = 0


# ── Shared damage helpers ──────────────────────────────────────────────────────

def _hit_enemy(
    session: "CombatSession",
    target:  EnemyEntity,
    amount:  float,
    dtype:   str,
    caster:  WarframeEntity,
    log:     list[str],
) -> int:
    """
    Apply outgoing damage from player to one enemy.
    Applies damage_multiplier() (Speed buff, Exalted Blade flag) and the
    Electric Shield ranged bonus.  Logs with the correct damage-type emoji.
    """
    raw = float(amount)
    raw *= caster.damage_multiplier()

    if dtype not in ("slash", "impact") and getattr(session, "electric_shield_active", False):
        stacks = getattr(session, "electric_shield_stacks", 1)
        raw   *= (1 + 0.5 * stacks)

    hp_dmg = target.take_damage(raw, dtype)
    icon   = dmg_icon(dtype)

    if hp_dmg > 0:
        log.append(
            f"{_STAT_NEG} **{target.name}** takes **{int(raw)}** {icon} {dtype} dmg! "
            f"(HP: {target.hp}/{target.max_hp})"
        )
    else:
        log.append(
            f"{_SHIELD} **{target.name}**'s shields absorb **{int(raw)}** {icon} {dtype}! "
            f"(Shields: {target.shields}/{target.max_shields})"
        )

    if not target.is_alive:
        log.append(f"{_DOWN} **{target.name}** defeated!")
    return hp_dmg


def _proc_chance(
    target:  EnemyEntity,
    dtype:   str,
    caster:  WarframeEntity,
    log:     list[str],
    chance:  float = 0.25,
    source:  str   = "",
) -> None:
    """Roll a proc for a given damage type on a surviving enemy."""
    if not target.is_alive:
        return
    if random.random() > chance:
        return

    src  = source or caster.name
    icon = dmg_icon(dtype)

    if dtype == "slash":
        mag = 15
        target.apply_status(make_slash_bleed(mag, src))
        log.append(
            f"  {icon} **{target.name}** Bleeds! "
            f"({mag} {dmg_icon('true')} True dmg/turn × 2)"
        )
    elif dtype == "puncture":
        target.apply_status(make_puncture(src))
        log.append(f"  {icon} **{target.name}** Punctured! (-30% dmg on next attack)")
    elif dtype == "impact":
        target.apply_status(make_impact(src))
        log.append(f"  {icon} **{target.name}** Staggered! (-25% shield regen, 1t)")
    elif dtype == "electricity":
        target.apply_status(make_electric(40, src))
        log.append(f"  {icon} **{target.name}** Electric proc! (arcs to adjacent enemy)")
    elif dtype == "magnetic":
        target.apply_status(make_magnetic_proc(src))
        log.append(
            f"  {icon} **{target.name}** Magnetic proc! "
            f"(shields drained, -50% max shields, 2t)"
        )
    elif dtype == "blast":
        target.apply_status(make_blast(src))
        target.apply_status(make_knockdown(src))
        log.append(
            f"  {icon} **{target.name}** Blasted! (Knockdown + -25% accuracy, 1t)"
        )
    elif dtype == "heat":
        target.apply_status(make_heat(12, src))
        log.append(
            f"  {icon} **{target.name}** Burning! "
            f"(12 {dmg_icon('heat')} Heat dmg/turn × 2, -50% armor)"
        )
    elif dtype == "cold":
        target.apply_status(make_cold(src))
        log.append(f"  {icon} **{target.name}** Chilled! (-30% damage output, 2t)")
    elif dtype == "toxin":
        target.apply_status(make_toxin(14, src))
        log.append(
            f"  {icon} **{target.name}** Poisoned! "
            f"(14 {dmg_icon('toxin')} Toxin dmg/turn × 2, bypasses shields)"
        )
    elif dtype == "radiation":
        target.apply_status(make_radiation(src))
        log.append(
            f"  {icon} **{target.name}** Irradiated! "
            f"(25% chance to attack allies, 2t)"
        )
    elif dtype == "viral":
        target.apply_status(make_viral(src))
        log.append(f"  {icon} **{target.name}** Viral! (effective max HP halved, 2t)")
    elif dtype == "corrosive":
        target.apply_status(make_corrosive(0.15, src))
        log.append(
            f"  {icon} **{target.name}** Corroded! "
            f"(-15% base armor permanently, max 4 stacks)"
        )
    elif dtype == "gas":
        target.apply_status(make_gas(18, src))
        log.append(
            f"  {icon} **{target.name}** Gas Cloud! "
            f"(18 {dmg_icon('toxin')} Toxin dmg/turn × 2 AoE)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# WEAPON ATTACKS
# ─────────────────────────────────────────────────────────────────────────────

def basic_attack(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """
    Primary weapon attack — reads session.primary_weapon_name from WEAPON_STATS.

    Braton: 3 hits per action, crit + proc rolled per hit.
    Paris:  1 charged arrow, Punch-Through on all enemies in line, silent.
    Volt Static Discharge releases on any weapon attack.
    """
    from combat.weapons import WEAPON_STATS, roll_crit, weighted_proc_type as _pick_proc

    result = AbilityResult(used_energy=0)

    wp = WEAPON_STATS.get(session.primary_weapon_name, WEAPON_STATS["MK1-Braton"])

    # Target selection — punch-through hits every living enemy
    if wp["punch_through"]:
        targets = session.living_enemies()
    else:
        t = session.get_primary_target()
        targets = [t] if t else []

    if not targets:
        result.log.append("No targets remaining.")
        return result

    # Header
    silence_tag = "  🔇 *Silent.*" if wp["silent"] else ""
    result.log.append(
        f"{wp['emoji']} **{wp['action_label']}** — {session.primary_weapon_name}!{silence_tag}"
    )
    if wp["punch_through"]:
        result.log.append(
            f"  {_PUNCT} **Punch-Through** — arrow pierces every enemy in the line!"
        )

    # Outgoing multipliers
    spd_mult      = 1.5 if caster.speed_active else 1.0
    shield_stacks = getattr(session, "electric_shield_stacks", 1)
    shield_mult   = (
        (1.0 + 0.5 * shield_stacks)
        if getattr(session, "electric_shield_active", False)
        else 1.0
    )

    # Per-target rolls
    for target in targets:
        if not target.is_alive:
            continue

        hits       = wp["hits_per_action"]
        total_raw  = 0.0
        crit_count = 0
        proc_dtype = None

        for _ in range(hits):
            base         = wp["total_per_hit"] * spd_mult * shield_mult
            final, crit  = roll_crit(base, wp["crit_chance"], wp["crit_mult"])
            total_raw   += final
            if crit:
                crit_count += 1
            if random.random() < wp["status_chance"]:
                proc_dtype = _pick_proc(wp["damage_per_hit"])

        dtype    = _pick_proc(wp["damage_per_hit"])
        icon     = dmg_icon(dtype)
        hp_dmg   = target.take_damage(total_raw, dtype)
        crit_str = f" — **CRIT ×{crit_count}!**" if crit_count else ""
        hit_note = f" *({hits} hits)*" if hits > 1 else ""

        if hp_dmg > 0:
            result.log.append(
                f"{_STAT_NEG} **{target.name}** takes **{int(total_raw)}** {icon} {dtype}"
                f"{hit_note}{crit_str}  (HP: {target.hp}/{target.max_hp})"
            )
        else:
            result.log.append(
                f"{_SHIELD} **{target.name}**'s shields absorb **{int(total_raw)}** {icon}!"
                f"{crit_str}  (Shields: {target.shields}/{target.max_shields})"
            )

        result.dealt_damage += int(total_raw)

        if not target.is_alive:
            result.log.append(f"{_DOWN} **{target.name}** defeated!")
        elif proc_dtype:
            _proc_chance(target, proc_dtype, caster, result.log, chance=1.0)

    # VOLT: Static Discharge
    if caster.warframe_key == "volt" and caster.static_charges > 0:
        bonus   = caster.static_charges * 18
        primary = targets[0] if targets else session.get_primary_target()
        if primary and primary.is_alive:
            result.log.append(
                f"{_ELEC} Static Discharge — **{caster.static_charges}** charges release "
                f"(+**{bonus}** {_ELEC} Electricity)!"
            )
            _hit_enemy(session, primary, bonus, "electricity", caster, result.log)
            _proc_chance(primary, "electricity", caster, result.log, chance=0.35)
            result.dealt_damage += bonus
        caster.static_charges = 0

    caster.combo_gauge += 1
    result.log.append(f"{_COMBO} Combo Gauge: **{caster.combo_gauge}** stacks")
    return result


def melee_attack(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """
    Melee weapon attack — reads session.melee_weapon_name from WEAPON_STATS.

    When Exalted Blade is active, fires a piercing energy wave through all
    remaining enemies behind the primary target.
    Finisher (×8 dmg) triggers if the primary target is Blinded.
    Excalibur passive: +10% damage when wielding a sword (from weapon's excalibur_bonus).
    Combo gauge builds +2 per melee hit (vs +1 for ranged).
    """
    from combat.weapons import WEAPON_STATS, roll_crit

    result  = AbilityResult(used_energy=0)
    wp_name = session.melee_weapon_name
    wp      = WEAPON_STATS.get(wp_name, WEAPON_STATS["Skana"])

    target = session.get_primary_target()
    if not target:
        result.log.append("No targets remaining.")
        return result

    # Finisher (melee-exclusive)
    is_finisher = target.has_status(StatusType.BLIND)
    fin_mult    = 8.0 if is_finisher else 1.0
    if is_finisher:
        result.log.append(
            f"{_RADIAL_BL} **FINISHER!** **{target.name}** is Blinded — "
            f"**×8 melee damage bonus!**"
        )

    # Header — reflect Exalted Blade if active
    if caster.exalted_active:
        result.log.append(
            f"{_EXALTED} **Exalted Blade** — ethereal {wp_name} strikes **{target.name}**!"
        )
    else:
        result.log.append(f"{wp['emoji']} **{wp['action_label']}** — {wp_name}!")

    # Combo gauge bonus (+5% per stack)
    combo_mult = 1.0 + caster.combo_gauge * 0.05
    if caster.combo_gauge > 0:
        result.log.append(
            f"{_COMBO} Combo ×{combo_mult:.2f} active ({caster.combo_gauge} stacks)"
        )

    # Outgoing multipliers
    spd_mult   = 1.5 if caster.speed_active else 1.0
    excal_mult = (1.0 + wp["excalibur_bonus"]) if caster.warframe_key == "excalibur" else 1.0
    base       = wp["total_per_hit"] * spd_mult * excal_mult * combo_mult * fin_mult

    final, is_crit = roll_crit(base, wp["crit_chance"], wp["crit_mult"])
    if is_crit:
        result.log.append(f"  💥 **CRITICAL!** ×{wp['crit_mult']}")

    # Damage application (slash-dominant → bypass armor)
    dtype  = "slash"
    icon   = dmg_icon(dtype)
    hp_dmg = target.take_damage(final, dtype)

    if hp_dmg > 0:
        result.log.append(
            f"{_STAT_NEG} **{target.name}** takes **{int(final)}** {icon} slash! "
            f"(HP: {target.hp}/{target.max_hp})"
        )
    else:
        result.log.append(
            f"{_SHIELD} **{target.name}**'s shields absorb **{int(final)}** {icon}! "
            f"(Shields: {target.shields}/{target.max_shields})"
        )

    result.dealt_damage += int(final)

    if not target.is_alive:
        result.log.append(f"{_DOWN} **{target.name}** defeated!")
    elif random.random() < wp["status_chance"]:
        _proc_chance(target, "slash", caster, result.log, chance=1.0)

    # Exalted Blade: energy wave pierces all other living enemies
    if caster.exalted_active:
        others = [e for e in session.living_enemies() if e is not target]
        if others:
            result.log.append(f"{_EXALTED} Energy wave fires through the line!")
            wave_base = final * 0.6
            for other in others:
                wave_dmg = other.take_damage(wave_base, "slash")
                if wave_dmg > 0:
                    result.log.append(
                        f"  {_STAT_NEG} **{other.name}** hit for **{int(wave_base)}** "
                        f"{icon} slash! (HP: {other.hp}/{other.max_hp})"
                    )
                else:
                    result.log.append(
                        f"  {_SHIELD} **{other.name}**'s shields absorb wave "
                        f"**{int(wave_base)}** {icon}!"
                    )
                if not other.is_alive:
                    result.log.append(f"  {_DOWN} **{other.name}** defeated!")
                result.dealt_damage += int(wave_base)

    # Combo gauge: +2 for melee
    caster.combo_gauge += 2
    result.log.append(
        f"{_COMBO} Combo Gauge: **{caster.combo_gauge}** stacks  *(+2 melee bonus)*"
    )
    return result


def secondary_attack(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """
    Secondary weapon attack — reads session.secondary_weapon_name from WEAPON_STATS.

    Lato: slight Slash lean, 10% crit, 1.5×, 10% status chance.
    Volt Static Discharge also releases on secondary attacks.
    """
    from combat.weapons import WEAPON_STATS, roll_crit, weighted_proc_type as _pick_proc

    result  = AbilityResult(used_energy=0)
    wp_name = session.secondary_weapon_name
    wp      = WEAPON_STATS.get(wp_name, WEAPON_STATS["Lato"])

    target = session.get_primary_target()
    if not target:
        result.log.append("No targets remaining.")
        return result

    result.log.append(f"{wp['emoji']} **{wp['action_label']}** — {wp_name}!")

    # Outgoing multipliers
    spd_mult    = 1.5 if caster.speed_active else 1.0
    base        = wp["total_per_hit"] * spd_mult
    final, crit = roll_crit(base, wp["crit_chance"], wp["crit_mult"])
    crit_str    = f" — **CRIT!** ×{wp['crit_mult']}" if crit else ""

    dtype  = _pick_proc(wp["damage_per_hit"])
    icon   = dmg_icon(dtype)
    hp_dmg = target.take_damage(final, dtype)

    if hp_dmg > 0:
        result.log.append(
            f"{_STAT_NEG} **{target.name}** takes **{int(final)}** {icon} {dtype}{crit_str}! "
            f"(HP: {target.hp}/{target.max_hp})"
        )
    else:
        result.log.append(
            f"{_SHIELD} Shields absorb **{int(final)}** {icon}{crit_str}! "
            f"(Shields: {target.shields}/{target.max_shields})"
        )

    result.dealt_damage += int(final)

    if not target.is_alive:
        result.log.append(f"{_DOWN} **{target.name}** defeated!")
    elif random.random() < wp["status_chance"]:
        _proc_chance(target, dtype, caster, result.log, chance=1.0)

    # VOLT: Static Discharge
    if caster.warframe_key == "volt" and caster.static_charges > 0:
        bonus = caster.static_charges * 18
        if target.is_alive:
            result.log.append(
                f"{_ELEC} Static Discharge — **{caster.static_charges}** charges release "
                f"(+**{bonus}** {_ELEC} Electricity)!"
            )
            _hit_enemy(session, target, bonus, "electricity", caster, result.log)
            result.dealt_damage += bonus
        caster.static_charges = 0

    caster.combo_gauge += 1
    result.log.append(f"{_COMBO} Combo Gauge: **{caster.combo_gauge}** stacks")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# EXCALIBUR
# ─────────────────────────────────────────────────────────────────────────────

def excalibur_slash_dash(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Slash Dash — 25 Energy. Strikes ALL enemies; untargetable this turn."""
    result  = AbilityResult(used_energy=25)
    enemies = session.living_enemies()
    if not enemies:
        result.log.append("No targets.")
        return result

    session.player_untargetable = True
    base = 100 if not caster.exalted_active else 130
    base = int(base * (1 + caster.combo_gauge * 0.05))

    result.log.append(
        f"{_SLASH_DASH} **Slash Dash** — {caster.name} tears through the line! "
        f"*(Untargetable this turn)*"
    )

    for enemy in enemies:
        _hit_enemy(session, enemy, base, "slash", caster, result.log)
        result.dealt_damage += base

        if enemy.is_alive:
            bleed_mag = int(base * 0.35)
            enemy.apply_status(make_slash_bleed(bleed_mag, caster.name))
            result.log.append(
                f"  {dmg_icon('slash')} **{enemy.name}** inflicted with Bleed! "
                f"({bleed_mag} {dmg_icon('true')} True dmg/turn × 2)"
            )
            enemy.apply_status(make_knockdown(caster.name))
            result.log.append(
                f"  {_KNOCKDOWN} **{enemy.name}** Knocked Down! (skips next turn)"
            )

        if caster.exalted_active and enemy.is_alive:
            result.log.append(
                f"  {_SLASH_DASH} Exalted energy wave pierces through **{enemy.name}**!"
            )

        caster.combo_gauge += 1

    result.log.append(f"{_COMBO} Combo Gauge: **{caster.combo_gauge}** stacks")
    return result


def excalibur_radial_blind(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Radial Blind — 50 Energy. Blinds ALL enemies for 2 turns."""
    result  = AbilityResult(used_energy=50)
    enemies = session.living_enemies()
    if not enemies:
        result.log.append("No targets.")
        return result

    result.log.append(
        f"{_RADIAL_BL} **Radial Blind** — A blinding flash engulfs every enemy!"
    )

    melee_name = session.melee_weapon_name
    mw         = __import__("combat.weapons", fromlist=["WEAPON_STATS"]).WEAPON_STATS
    melee_emoji = mw.get(melee_name, {}).get("emoji", "")

    for enemy in enemies:
        enemy.apply_status(make_blind(duration=2, source=caster.name))
        result.log.append(
            f"  {_RADIAL_BL} **{enemy.name}** Blinded for 2 turns! "
            f"*(Use {melee_emoji} **{melee_name}** for an **×8 Finisher** strike!)*"
        )

    result.log.append(
        f"{_LOTUS} **TIP:** Use {melee_emoji} **{melee_name}** on a Blinded enemy "
        f"for an **800% Finisher** bonus!"
    )
    return result


def excalibur_radial_javelin(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Radial Javelin — 75 Energy. Hurls javelins at ALL enemies simultaneously."""
    result  = AbilityResult(used_energy=75)
    enemies = session.living_enemies()
    if not enemies:
        result.log.append("No targets.")
        return result

    result.log.append(
        f"{_RAD_JAV} **Radial Javelin** — Ethereal javelins rain down on every enemy!"
    )
    base = 130

    for enemy in enemies:
        _hit_enemy(session, enemy, base, "slash", caster, result.log)
        result.dealt_damage += base

        if enemy.is_alive:
            bleed_mag = int(base * 0.3)
            enemy.apply_status(make_slash_bleed(bleed_mag, caster.name))
            result.log.append(
                f"  {dmg_icon('slash')} **{enemy.name}** Bleeds! "
                f"({bleed_mag} {dmg_icon('true')} True dmg/turn × 2)"
            )
            enemy.apply_status(make_stunned(1, caster.name))
            result.log.append(f"  {_STUNNED} **{enemy.name}** Stunned for 1 turn!")

    return result


def excalibur_exalted_blade(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Exalted Blade — 25 Energy to activate + 1.25 Energy/turn drain. Toggleable."""
    melee_name = session.melee_weapon_name
    from combat.weapons import WEAPON_STATS
    mw_emoji = WEAPON_STATS.get(melee_name, {}).get("emoji", "")

    if caster.exalted_active:
        caster.exalted_active = False
        session.unregister_turn_drain("exalted_blade")
        return AbilityResult(
            used_energy=0,
            log=[f"{_EXALTED} **Exalted Blade** deactivated — energy drain stopped."],
        )

    caster.exalted_active = True
    session.register_turn_drain("exalted_blade", caster, 1.25)

    return AbilityResult(
        used_energy=25,
        log=[
            f"{_EXALTED} **Exalted Blade** — An ethereal {melee_name} materializes!",
            f"  • Use {mw_emoji} **{melee_name}** to fire piercing energy waves through the line",
            "  • **Slash Dash** gains +30 base damage",
            f"  • Costs **1.25 {_ENERGY} Energy/turn** — cast again to deactivate",
            f"  • Current Energy: {caster.energy - 25}/{caster.max_energy}",
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAG
# ─────────────────────────────────────────────────────────────────────────────

def mag_pull(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Pull — 25 Energy. Magnetic vortex: Magnetic damage + Knockdown on ALL enemies."""
    result  = AbilityResult(used_energy=25)
    enemies = session.living_enemies()
    if not enemies:
        result.log.append("No targets.")
        return result

    result.log.append(
        f"{_PULL} **Pull** — Mag's magnetic vortex slams every enemy forward!"
    )
    base = 75

    for enemy in enemies:
        _hit_enemy(session, enemy, base, "magnetic", caster, result.log)
        result.dealt_damage += base
        if enemy.is_alive:
            enemy.apply_status(make_magnetic_proc(caster.name))
            result.log.append(
                f"  {dmg_icon('magnetic')} **{enemy.name}** Magnetic proc! "
                f"(shields drained, -50% max shields, 2t)"
            )
            enemy.apply_status(make_knockdown(caster.name))
            result.log.append(f"  {_KNOCKDOWN} **{enemy.name}** Knocked Down!")

    if caster.has_status(StatusType.POLARIZE_SHARD):
        session.polarize_shards_absorbed = True
        result.log.append(
            f"{_POLARIZE} Polarize Shards drawn in by Pull — "
            f"**Magnetize explosion amplified** when it detonates!"
        )

    return result


def mag_magnetize(
    session: "CombatSession",
    caster:  WarframeEntity,
    hold:    bool = False,
) -> AbilityResult:
    """
    Magnetize — 50 Energy.
    CAST:      Enclose primary target for 3 turns: Anchored, all damage ×2, explodes.
    HOLD CAST: Absorb all ranged attacks this turn; release as a burst.
    """
    result = AbilityResult(used_energy=50)

    if hold:
        caster.magnetize_absorb = True
        caster.magnetize_stored = 0
        result.log.append(
            f"{_MAGNETIZE} **Magnetize (Hold)** — Mag forms a defensive singularity!\n"
            f"  • All incoming ranged attacks **absorbed** this turn\n"
            f"  • Stored damage releases as a targeted burst next action"
        )
        return result

    target = session.get_primary_target()
    if not target:
        result.log.append("No targets.")
        return result

    target.apply_status(make_magnetized(duration=3, source=caster.name))
    session.magnetize_target = target
    session.magnetize_turns  = 3

    result.log.append(
        f"{_MAGNETIZE} **Magnetize** — **{target.name}** trapped in a magnetic field for 3 turns!\n"
        f"  • **Anchored** — cannot act\n"
        f"  • All ranged attacks **redirected** into this target\n"
        f"  • **All damage ×2**\n"
        f"  • Will **explode** for {_BLAST_ICON} Blast dmg when field expires!"
    )
    return result


def mag_polarize(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Polarize — 75 Energy. Strips ALL enemy shields + armor; restores Mag's shields."""
    result  = AbilityResult(used_energy=75)
    enemies = session.living_enemies()

    result.log.append(
        f"{_POLARIZE} **Polarize** — A magnetic pulse strips shields and armor from every enemy!"
    )

    for enemy in enemies:
        stripped_sh  = enemy.shields
        stripped_arm = int(enemy.armor * 0.45)

        enemy.shields = 0
        enemy.armor   = max(0, enemy.armor - stripped_arm)

        mag_dmg = stripped_sh + stripped_arm
        if mag_dmg > 0:
            _hit_enemy(session, enemy, mag_dmg, "magnetic", caster, result.log)
            result.dealt_damage += mag_dmg

        result.log.append(
            f"  <:wf_shield:1499636531755745280> **{enemy.name}**: "
            f"-{stripped_sh} Shields, -{stripped_arm} Armor stripped!"
        )

    restored = caster.restore_shields(80)
    result.log.append(
        f"<:wf_shield:1499636531755745280> Mag's shields restored by **{restored}**! "
        f"({caster.shields}/{caster.max_shields})"
    )

    caster.apply_status(make_polarize_shard(damage_per_turn=22.0, duration=3, source=caster.name))
    result.log.append(
        f"{_POLARIZE} **Polarize Shards** now orbit Mag!\n"
        f"  • 22 {_PUNCT} Puncture / {dmg_icon('slash')} Slash dmg to enemies each End Phase\n"
        f"  • **Pull** draws them in → amplifies Magnetize explosion"
    )

    return result


def mag_crush(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Crush — 100 Energy. 3 successive Magnetic waves vs ALL enemies."""
    result = AbilityResult(used_energy=100)
    result.log.append(
        f"{_CRUSH} **Crush** — Mag magnetizes the bones of every enemy! **3 waves incoming…**"
    )

    for wave in range(1, 4):
        result.log.append(f"  {_CRUSH} **Wave {wave}:**")
        for enemy in session.living_enemies():
            base      = 85
            mag_bonus = 0
            if enemy.has_status(StatusType.MAGNETIZED):
                mag_bonus = 110
                result.log.append(
                    f"    {_MAGNETIZE} Magnetize synergy on **{enemy.name}**! (+{mag_bonus})"
                )
            _hit_enemy(session, enemy, base + mag_bonus, "magnetic", caster, result.log)
            result.dealt_damage += base + mag_bonus

        restored = caster.restore_shields(25)
        result.log.append(
            f"    <:wf_shield:1499636531755745280> Shields restored +{restored} "
            f"({caster.shields}/{caster.max_shields})"
        )

    for enemy in session.living_enemies():
        enemy.apply_status(make_knockdown(caster.name))
        result.log.append(
            f"  {_KNOCKDOWN} **{enemy.name}** Knocked Down by the final crushing wave!"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# VOLT
# ─────────────────────────────────────────────────────────────────────────────

def volt_shock(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Shock — 25 Energy. Voltaic arc chains up to 3 enemies. Stuns primary target 1 turn."""
    result  = AbilityResult(used_energy=25)
    enemies = session.living_enemies()
    if not enemies:
        result.log.append("No targets.")
        return result

    chain_targets = enemies[:3]
    result.log.append(
        f"{_SHOCK} **Shock** — Volt's arc chains through {len(chain_targets)} target(s)!"
    )

    for i, target in enumerate(chain_targets):
        base = 95 if i == 0 else 60
        _hit_enemy(session, target, base, "electricity", caster, result.log)
        result.dealt_damage += base

        if i == 0 and target.is_alive:
            target.apply_status(make_stunned(1, caster.name))
            result.log.append(f"  {_STUNNED} **{target.name}** Stunned for 1 turn!")

        if target.is_alive and i > 0:
            target.apply_status(make_electric(35, caster.name))
            result.log.append(
                f"  {_ELEC} **{target.name}** Electric proc! (arcs to adjacent)"
            )

        if target.has_status(StatusType.TESLA_COIL) and target.is_alive:
            result.log.append(
                f"  {_BLAST_ICON} **Overcharge Burst** triggered on **{target.name}**!"
            )
            for adj in session.living_enemies():
                if adj is not target:
                    _hit_enemy(session, adj, 55, "electricity", caster, result.log)
                    result.dealt_damage += 55

    if getattr(session, "electric_shield_active", False):
        session.electric_shield_electrified = True
        result.log.append(
            f"{_EL_SHIELD} Electric Shield **Electrified** — "
            f"enemies attacking through it take {_ELEC} Electricity dmg!"
        )

    return result


def volt_speed(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Speed — 25 Energy. +50% damage for 2 turns. Bonus action this round."""
    caster.speed_active = True
    caster.speed_turns  = 2
    caster.apply_status(make_speed_buff(duration=2, source=caster.name))
    session.bonus_actions += 1

    return AbilityResult(
        used_energy=25,
        log=[
            f"{_SPEED} **Speed** — Volt surges with electrical energy!",
            "  • **+50% damage** on all actions for 2 turns",
            "  • **Bonus action** granted this round *(3 total actions available)*",
            "  • All active cooldowns reduced by 1 turn",
        ],
    )


def volt_electric_shield(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Electric Shield — 50 Energy. Blocks ALL ranged attacks for 3 turns."""
    if getattr(session, "electric_shield_active", False):
        session.electric_shield_stacks = getattr(session, "electric_shield_stacks", 1) + 1
        return AbilityResult(
            used_energy=50,
            log=[
                f"{_EL_SHIELD} **Electric Shield** stacked! "
                f"(×{session.electric_shield_stacks} bonus active)",
                f"  • +{50 * session.electric_shield_stacks}% total {_ELEC} Electricity bonus",
            ],
        )

    session.electric_shield_active      = True
    session.electric_shield_turns       = 3
    session.electric_shield_stacks      = 1
    session.electric_shield_electrified = False

    return AbilityResult(
        used_energy=50,
        log=[
            f"{_EL_SHIELD} **Electric Shield** erected for 3 turns!",
            "  • **Blocks all incoming ranged attacks**",
            f"  • Your ranged attacks through it: +50% {_ELEC} Electricity, ×2 critical",
            f"  • Cast **Shock** through it to **Electrify** the barrier!",
        ],
    )


def volt_discharge(session: "CombatSession", caster: WarframeEntity) -> AbilityResult:
    """Discharge — 100 Energy. Massive electric pulse; hits ALL enemies. Stuns 2t + Tesla Coil."""
    result  = AbilityResult(used_energy=100)
    enemies = session.living_enemies()
    if not enemies:
        result.log.append("No targets.")
        return result

    result.log.append(
        f"{_DISCHARGE} **Discharge** — A massive electric pulse erupts, ignoring all cover!"
    )
    arc_dmg = 55

    for enemy in enemies:
        _hit_enemy(session, enemy, 160, "electricity", caster, result.log)
        result.dealt_damage += 160

        if enemy.is_alive:
            enemy.apply_status(make_stunned(2, caster.name))
            enemy.apply_status(make_tesla_coil(arc_dmg, 2, caster.name))
            result.log.append(
                f"  {_DISCHARGE} **{enemy.name}** Stunned (2t) + Tesla Coil! "
                f"(arcs **{arc_dmg}** {_ELEC} Electricity to adjacents each End Phase)"
            )

    result.log.append(
        f"{_LOTUS} **TIP:** Use **Shock** on any Stunned enemy to trigger "
        f"an **Overcharge Burst** on all adjacents!"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch tables — add a new warframe by editing ONLY these dicts.
# ─────────────────────────────────────────────────────────────────────────────

ABILITY_MAP: dict[str, list] = {
    "excalibur": [
        excalibur_slash_dash,
        excalibur_radial_blind,
        excalibur_radial_javelin,
        excalibur_exalted_blade,
    ],
    "mag": [
        mag_pull,
        mag_magnetize,
        mag_polarize,
        mag_crush,
    ],
    "volt": [
        volt_shock,
        volt_speed,
        volt_electric_shield,
        volt_discharge,
    ],
}

DEFAULT_ABILITY_COSTS: list[int] = [25, 50, 75, 100]

ABILITY_COSTS: dict[str, list[int]] = {
    "excalibur": [25, 50, 75, 100],
    "mag":       [25, 50, 75, 100],
    "volt":      [25, 25, 50, 100],
}

TOGGLE_ABILITY_INDEX: dict[str, int] = {
    "excalibur": 3,
}

TOGGLE_FLAG_KEY: dict[str, str] = {
    "excalibur": "exalted_active",
}

HOLD_CAST_ABILITIES: dict[str, set[int]] = {
    "mag": {1},
}

PASSIVE_DAMAGE_BONUS: dict[str, object] = {
    "excalibur": lambda flags: 0.10 if flags.get("exalted_active") else 0.0,
    "volt":      lambda flags: 0.50 if flags.get("speed_active")   else 0.0,
}

ABILITY_DATA: dict[str, dict] = {
    "excalibur": {
        "slash_dash_base":              100,
        "slash_dash_exalted_bonus":      30,
        "slash_dash_bleed_ratio":        0.35,
        "radial_javelin_base":          130,
        "radial_javelin_bleed_ratio":    0.30,
        "exalted_wave_ratio":            0.60,
        "exalted_turn_drain":            1.25,
        "exalted_activate_cost":         25,
    },
    "mag": {
        "pull_base":                     75,
        "crush_wave_base":               85,
        "crush_magnetize_bonus":        110,
        "crush_shield_restore_per_wave": 25,
        "magnetize_explosion_base":     140,
        "polarize_shard_bonus":          90,
        "magnetize_splash_ratio":        0.50,
        "magnetize_duration":            3,
        "polarize_strip_ratio":          0.45,
        "polarize_shield_restore":       80,
        "polarize_shard_damage":         22.0,
        "polarize_shard_duration":       3,
    },
    "volt": {
        "shock_primary":                 95,
        "shock_chain":                   60,
        "shock_overcharge_burst":        55,
        "shock_stun_turns":               1,
        "electric_shield_zap":           65,
        "electric_shield_turns":          3,
        "discharge_base":               160,
        "discharge_arc":                 55,
        "discharge_stun_turns":           2,
        "speed_damage_bonus":            0.50,
        "speed_turns":                    2,
    },
}

# ── Per-warframe turn-start passive log lines ──────────────────────────────────

def warframe_turn_start_log(session: "CombatSession", player: "WarframeEntity") -> list[str]:
    fn = TURN_START_LOG_FNS.get(player.warframe_key)
    return fn(session, player) if fn else []

_ELEC_ICON = "<:electricity:1499596184958795917>"
_MAG_ICON  = "<:magnetize:1499595149091668103>"

TURN_START_LOG_FNS: dict[str, object] = {
    "volt": lambda session, player: (
        [
            f"{_ELEC_ICON} Static Discharge: **{player.static_charges}/5** charges "
            f"(release on next Basic Attack)"
        ]
        if player.static_charges > 0 else []
    ),
    "mag": lambda session, player: [
        f"{_MAG_ICON} **Mag Passive** — All field orbs auto-collected."
    ],
}

STATIC_CHARGE_WARFRAMES: set[str] = {"volt"}
SPEED_BUFF_WARFRAMES: set[str] = {"volt"}


def use_ability(
    session: "CombatSession",
    caster:  WarframeEntity,
    index:   int,
    hold:    bool = False,
) -> AbilityResult:
    fns = ABILITY_MAP.get(caster.warframe_key, [])
    if index < 0 or index >= len(fns):
        return AbilityResult(used_energy=0, log=["Unknown ability index."])
    fn = fns[index]
    if index in HOLD_CAST_ABILITIES.get(caster.warframe_key, set()):
        return fn(session, caster, hold=hold)
    return fn(session, caster)
