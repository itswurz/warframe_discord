# utils/combat_embeds.py
# ─────────────────────────────────────────────────────────────────────────────
# Builds the Discord embeds shown during and after combat.
#
# build_combat_embed()  — live combat embed (called after every action)
# build_loot_embed()    — post-mission reward summary (sent once on victory/defeat)
#
# Mission Loot field (added to build_combat_embed):
#   Shows an aggregated running tally of every drop collected so far.
#   Resources are summed by name; mods and cosmetics are listed individually.
#   Only rendered when at least one drop exists.
# ─────────────────────────────────────────────────────────────────────────────

import discord
from combat.session import CombatSession, CombatState, MAX_ACTIONS
from combat.status import StatusType
from data.warframes import WARFRAMES
from utils.emojis import E

DEFAULT_COLOR  = 0x1F4E5F
VICTORY_COLOR  = 0x1A7A3C
DEFEAT_COLOR   = 0x7B1515

# ── Loot type labels ──────────────────────────────────────────────────────────
_RARITY_LABEL = {
    "common":    "C",
    "uncommon":  "U",
    "rare":      "R",
    "cosmetic":  "✦",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_loot(mission_loot: list[dict]) -> list[str]:
    """
    Produce a compact list of strings for the Mission Loot embed field.
    Resources and Endo are summed by name; mods and cosmetics are listed once each.
    """
    resource_totals: dict[str, dict] = {}   # name → {amount, emoji}
    endo_total = 0
    endo_emoji = E.endo
    mod_lines:  list[str] = []
    cosm_lines: list[str] = []

    for drop in mission_loot:
        dtype  = drop["type"]
        name   = drop["name"]
        amount = drop["amount"]
        emoji  = drop["emoji"]

        if dtype == "resource":
            if name not in resource_totals:
                resource_totals[name] = {"amount": 0, "emoji": emoji}
            resource_totals[name]["amount"] += amount

        elif dtype == "endo":
            endo_total += amount
            endo_emoji  = emoji

        elif dtype == "mod":
            label = _RARITY_LABEL.get(drop.get("rarity", "common"), "C")
            mod_lines.append(f"{emoji} **{name}** `[{label}]`")

        elif dtype == "cosmetic":
            cosm_lines.append(f"{emoji} **{name}**")

    lines: list[str] = []
    for name, data in resource_totals.items():
        lines.append(f"{data['emoji']} **{name}** ×{data['amount']}")
    if endo_total:
        lines.append(f"{endo_emoji} **Endo** ×{endo_total}")
    lines.extend(mod_lines)
    lines.extend(cosm_lines)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Live combat embed
# ─────────────────────────────────────────────────────────────────────────────

def build_combat_embed(
    session:    CombatSession,
    recent_log: list[str] | None = None,
) -> discord.Embed:

    player  = session.player
    wf_data = WARFRAMES[player.warframe_key]

    # ── Accent color ──────────────────────────────────────────────────────────
    if session.state == CombatState.VICTORY:
        color = VICTORY_COLOR
    elif session.state == CombatState.DEFEAT:
        color = DEFEAT_COLOR
    else:
        color = DEFAULT_COLOR

    embed = discord.Embed(color=color)
    embed.set_author(
        name=f"MISSION  ·  Turn {session.turn}  ·  {player.name}",
        icon_url=wf_data["icon_url"],
    )

    # ── OPERATOR panel ────────────────────────────────────────────────────────
    energy_pct  = player.energy / max(1, player.max_energy)
    energy_icon = "<a:energy_orb:1499636329842212964>"

    operator_lines = [
        f"<a:health:1499636458309423215> HP:       `{player.hp_bar(12)}`",
        f"{E.shield} Shields:  `{player.shield_bar(10)}`",
        f"{energy_icon} Energy:   `{player.energy_bar(10)}`",
        f"{E.combo} Combo:    **{player.combo_gauge}** stack(s)  (+{player.combo_gauge * 5}% melee dmg)",
    ]

    if player.warframe_key == "volt" and player.static_charges > 0:
        operator_lines.append(
            f"{E.electricity} Static:   **{player.static_charges}/5** charges "
            f"(+{player.static_charges * 18} bonus on next attack)"
        )

    if player.warframe_key == "excalibur" and player.exalted_active:
        operator_lines.append(
            f"{E.exalted_blade} **Exalted Blade** — ACTIVE  "
            "(1.25 <a:energy_orb:1499636329842212964>/turn)"
        )

    if player.warframe_key == "mag" and player.magnetize_absorb:
        operator_lines.append(
            f"{E.magnetize} **Magnetize Absorb** — "
            f"{player.magnetize_stored} dmg stored"
        )

    status_str = player.status_icons()
    if status_str != "—":
        operator_lines.append(f"{E.lotus} Status:   {status_str}")

    embed.add_field(name="OPERATOR", value="\n".join(operator_lines), inline=False)

    # ── ENEMIES panel ─────────────────────────────────────────────────────────
    enemy_blocks: list[str] = []
    for enemy in session.enemies:
        if enemy.is_alive:
            hp_line = f"  <a:health:1499636458309423215> `{enemy.hp_bar(10)}`"
            sh_line = f"\n  {E.shield} `{enemy.shield_bar(8)}`" if enemy.max_shields else ""
            st_line = f"\n  {E.lotus} {enemy.status_icons()}"  if enemy.statuses   else ""
            block   = (
                f"{enemy.icon} **{enemy.name}** `[{enemy.faction}]`\n"
                f"{hp_line}{sh_line}{st_line}"
            )
        else:
            block = f"~~{enemy.icon} {enemy.name}~~  {E.down}"
        enemy_blocks.append(block)

    embed.add_field(
        name="ENEMIES",
        value="\n\n".join(enemy_blocks) or "All enemies defeated!",
        inline=False,
    )

    # ── FIELD EFFECTS panel ───────────────────────────────────────────────────
    effects: list[str] = []

    if session.electric_shield_active:
        elec_str = (
            f"{E.electric_shield} **Electric Shield** — "
            f"{session.electric_shield_turns}t remaining  "
            f"(×{session.electric_shield_stacks} stack)"
        )
        if session.electric_shield_electrified:
            elec_str += f"  {E.electricity} **Electrified**"
        effects.append(elec_str)

    if session.magnetize_target and session.magnetize_target.is_alive:
        effects.append(
            f"{E.magnetize} **Magnetize** on "
            f"**{session.magnetize_target.name}** — "
            f"{session.magnetize_turns}t until explosion"
        )

    if player.has_status(StatusType.POLARIZE_SHARD):
        shard = player.get_status(StatusType.POLARIZE_SHARD)
        effects.append(
            f"{E.polarize} **Polarize Shards** orbiting "
            f"({shard.duration}t) — "
            f"{int(shard.magnitude)} dmg/turn to all enemies"
        )

    if effects:
        embed.add_field(name="FIELD EFFECTS", value="\n".join(effects), inline=False)

    # ── MISSION LOOT field ────────────────────────────────────────────────────
    if session.mission_loot:
        loot_lines = _aggregate_loot(session.mission_loot)
        if loot_lines:
            embed.add_field(
                name="MISSION LOOT",
                value="\n".join(loot_lines)[:1020],
                inline=False,
            )

    # ── ACTIONS + ENERGY row ──────────────────────────────────────────────────
    if session.is_player_turn and not session.is_over:
        total = MAX_ACTIONS + session.bonus_actions
        rem   = session.actions_remaining
        pips  = "🟢" * rem + "⬛" * session.actions_used
        embed.add_field(
            name="ACTIONS",
            value=f"{pips}  **{rem}/{total}** remaining",
            inline=True,
        )
        embed.add_field(
            name="ENERGY",
            value=f"<a:energy_orb:1499636329842212964> **{player.energy}** / {player.max_energy}",
            inline=True,
        )

    # ── BATTLE LOG ────────────────────────────────────────────────────────────
    log_lines = (recent_log or session.log)[-10:]
    if log_lines:
        embed.add_field(
            name="BATTLE LOG",
            value="\n".join(log_lines)[:1020] or "…",
            inline=False,
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    if session.state == CombatState.VICTORY:
        embed.set_footer(text="✅  Mission Complete  ·  Ordis is proud, Operator.")
    elif session.state == CombatState.DEFEAT:
        embed.set_footer(text=f"{E.down}  Mission Failed  ·  The Lotus will not forget your sacrifice.")
    else:
        total = MAX_ACTIONS + session.bonus_actions
        embed.set_footer(
            text=(
                f"Turn {session.turn}  ·  "
                f"Actions: {session.actions_remaining}/{total}  ·  "
                f"Warframe © Digital Extremes"
            )
        )

    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Post-mission loot embed
# ─────────────────────────────────────────────────────────────────────────────

def build_loot_embed(session: CombatSession) -> discord.Embed:
    """
    Builds the end-of-mission reward summary embed.
    Sent once via interaction.followup.send() after victory or defeat.
    """
    is_victory = session.state == CombatState.VICTORY
    color = VICTORY_COLOR if is_victory else DEFEAT_COLOR

    if is_victory:
        title = f"{E.lotus}  Mission Complete — Reward Report"
        desc  = "All hostiles neutralised. The Lotus has logged your acquisitions, Operator."
    else:
        desc  = "You were defeated — but salvage teams recovered what they could."
        title = f"{E.lotus} Mission Failed — Salvaged Loot"

    embed = discord.Embed(title=title, description=desc, color=color)

    loot = session.mission_loot

    if not loot:
        embed.add_field(
            name="LOOT",
            value="*Nothing was collected this mission.*",
            inline=False,
        )
        embed.set_footer(text="Warframe © Digital Extremes")
        return embed

    # ── Aggregate by type ─────────────────────────────────────────────────────
    resource_totals: dict[str, dict] = {}
    endo_total  = 0
    endo_emoji  = "⚡"
    mods:   list[dict] = []
    cosms:  list[dict] = []

    for drop in loot:
        dtype = drop["type"]
        if dtype == "resource":
            n = drop["name"]
            if n not in resource_totals:
                resource_totals[n] = {"amount": 0, "emoji": drop["emoji"]}
            resource_totals[n]["amount"] += drop["amount"]
        elif dtype == "endo":
            endo_total += drop["amount"]
            endo_emoji  = drop["emoji"]
        elif dtype == "mod":
            mods.append(drop)
        elif dtype == "cosmetic":
            cosms.append(drop)

    # ── Resources field ───────────────────────────────────────────────────────
    res_lines: list[str] = []
    for name, data in resource_totals.items():
        res_lines.append(f"{data['emoji']} **{name}** ×{data['amount']}")
    if endo_total:
        res_lines.append(f"{endo_emoji} **Endo** ×{endo_total}")

    if res_lines:
        embed.add_field(
            name="RESOURCES & ENDO",
            value="\n".join(res_lines),
            inline=True,
        )

    # ── Mods field ────────────────────────────────────────────────────────────
    if mods:
        mod_lines: list[str] = []
        for mod in mods:
            rarity    = mod.get("rarity", "common")
            rlabel    = _RARITY_LABEL.get(rarity, "C")
            rarity_str = rarity.capitalize()
            mod_lines.append(
                f"{mod['emoji']} **{mod['name']}**  `[{rlabel}]` *{rarity_str}*"
            )
        embed.add_field(
            name="MODS",
            value="\n".join(mod_lines),
            inline=True,
        )

    # ── Cosmetics field ───────────────────────────────────────────────────────
    if cosms:
        cosm_lines = [f"{c['emoji']} **{c['name']}**" for c in cosms]
        embed.add_field(
            name="COSMETICS",
            value="\n".join(cosm_lines),
            inline=True,
        )

    # ── Summary footer ────────────────────────────────────────────────────────
    total_items = len(loot)
    mod_count   = len(mods)
    embed.set_footer(
        text=(
            f"{total_items} item(s) collected  ·  "
            f"{mod_count} mod(s) dropped  ·  "
            "Warframe © Digital Extremes"
        )
    )
    return embed
