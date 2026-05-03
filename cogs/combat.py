# cogs/combat.py
# ─────────────────────────────────────────────────────────────────────────────
# Discord cog that drives the turn-based combat loop.
#
# Entry point:   !combat  (or  !mission / !fight / !deploy)
#   • Loads the player's saved Warframe AND Primary weapon.
#   • Creates a CombatSession with the chosen loadout.
#   • Posts the initial combat embed + CombatView (button panel).
#
# CombatView button layout — FULLY DYNAMIC (reads WEAPON_STATS for all labels):
#   Row 0 — [Primary Weapon]  [Ability 1]  [Ability 2]  [Ability 3]  [Ability 4]
#   Row 1 — [End Turn]  [Melee Weapon]  [Secondary Weapon]  [Hold Cast*]  [📊 Status]
#            (* Hold Cast shown only for warframes with hold-cast abilities)
#
# Adding a new weapon:
#   1. Add it to combat/weapons.py WEAPON_STATS with "emoji" and "action_label".
#   2. Pass its name as melee_weapon / secondary_weapon when creating CombatSession.
#   All buttons update automatically — no code changes here needed.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from discord.ext import commands

from combat.session import CombatSession, CombatState, ACTIVE_SESSIONS
from combat.abilities import (
    ABILITY_COSTS, DEFAULT_ABILITY_COSTS,
    TOGGLE_ABILITY_INDEX, TOGGLE_FLAG_KEY,
    HOLD_CAST_ABILITIES,
)
from combat.weapons import WEAPON_STATS
from utils.combat_embeds import build_combat_embed, build_loot_embed
from data.warframes import WARFRAMES
from data import persistence
from utils.emojis import E


# ── Per-warframe ability button metadata ──────────────────────────────────────
# [emoji, short_label] for each of the four ability slots.
# Order matches ABILITY_MAP[warframe_key][0..3].

_ABILITY_META: dict[str, list[tuple[str, str]]] = {
    "excalibur": [
        (E.slash_dash,    "Slash Dash"),
        (E.radial_blind,   "Radial Blind"),
        (E.radial_javelin, "Radial Javelin"),
        (E.exalted_blade,  "Exalted Blade"),
    ],
    "mag": [
        (E.pull,      "Pull"),
        (E.magnetize, "Magnetize"),
        (E.polarize,  "Polarize"),
        (E.crush,     "Crush"),
    ],
    "volt": [
        (E.shock,          "Shock"),
        (E.speed,           "Speed"),
        (E.electric_shield, "Elec. Shield"),
        (E.discharge,       "Discharge"),
    ],
}

_NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]

# ── Hold-cast button metadata ─────────────────────────────────────────────────
# Maps warframe_key → (emoji, short_label, ability_index).
# Reads the ability's cost from ABILITY_COSTS automatically.

_HOLD_CAST_META: dict[str, tuple[str, str, int]] = {
    "mag": (E.magnetize, "Hold Cast", 1),
}

# ── Exalted override — when a toggle is active, replace the melee button ──────
# Maps warframe_key → (emoji, label) to show while the toggle is on
_MELEE_EXALTED_OVERRIDE: dict[str, tuple[str, str]] = {
    "excalibur": (E.exalted_blade, "Exalted"),
}

# ── Which ability_flags key indicates the melee override is active ─────────────
_MELEE_OVERRIDE_FLAG: dict[str, str] = {
    "excalibur": "exalted_active",
}


# ── Tutorial completion helper ────────────────────────────────────────────────

async def _finish_tutorial(
    interaction: discord.Interaction,
    session:     CombatSession,
) -> None:
    """Update the player profile and send the tutorial completion embed.

    Single load → single save per outcome so there is no intermediate state
    that a migration pass could corrupt between writes.
    """
    profile = await persistence.load_player(session.user_id)

    if session.state == CombatState.VICTORY:
        profile["initialized"]    = True
        profile["tutorial_step"]  = None
        profile["current_quest"]  = "vors_prize"
        profile["current_mission"] = "e_prime"
        completed_missions = profile.setdefault("completed_missions", [])
        if "awakening" not in completed_missions:
            completed_missions.append("awakening")
        await persistence.save_player(profile)

        color       = 0x1A7A3C
        title       = f"{E.lotus}  AWAKENING — COMPLETE"
        description = (
            "*\"Well done, Operator. The Grineer have been driven back — for now.\"*\n\n"
            "*\"But Captain Vor will not give up so easily. "
            "His prize — you — remains unclaimed.\"*\n\n"
            "*\"Your training is complete. The Origin System awaits you.\"*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"**Quest unlocked:** **Vor's Prize**\n"
            "Use `!quests` to view your Quest Log.\n"
            "Use `!warframe` to access your Orbiter."
        )
    else:
        profile["initialized"]    = False
        profile["tutorial_step"]  = "melee_select"
        profile["current_quest"]  = None
        profile["current_mission"] = None
        await persistence.save_player(profile)

        color       = 0x7B1515
        title       = f"{E.lotus}  AWAKENING — DEFEATED"
        description = (
            "*\"You have been overwhelmed, Operator. But do not despair.\"*\n\n"
            "*\"Your Warframe will recover. The Grineer have not yet found you.\"*\n\n"
            "Use `!warframe` to re-arm and try the Awakening again."
        )

    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Tutorial complete  ·  Warframe © Digital Extremes")
    await interaction.followup.send(embed=embed)


# ── Helper — rebuild embed + view, edit the message, send loot on end ──────────

async def _refresh(
    interaction: discord.Interaction,
    session:     CombatSession,
    log:         list[str],
) -> None:
    # Defer immediately so Discord doesn't time out the token while we do
    # DB work.  This gives us a 15-minute followup window instead of 3s.
    await interaction.response.defer()

    embed = build_combat_embed(session, log)

    if session.is_over:
        view = _disabled_view(session)
        # Stop the OLD view so its button callbacks no longer fire
        if hasattr(session, "_active_view") and session._active_view is not None:
            session._active_view.stop()
            session._active_view = None
    else:
        view = CombatView(session)
        session._active_view = view

    await interaction.edit_original_response(embed=embed, view=view)

    if session.is_over and not session.loot_posted:
        session.loot_posted = True
        ACTIVE_SESSIONS.pop(session.user_id, None)

        if session.tutorial:
            await _finish_tutorial(interaction, session)
            return

        try:
            from data.global_state import commit_session_to_profile
            await commit_session_to_profile(
                session        = session,
                display_name   = interaction.user.display_name,
                damage_dealt   = session.mission_damage_dealt,
                credits_earned = session.mission_credits_earned,
            )
        except Exception:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(
                "⚠️ Ordis encountered an error saving your profile. "
                "Your loot may not have been stored — please contact an admin.",
                ephemeral=True,
            )

        loot_embed = build_loot_embed(session)
        await interaction.followup.send(embed=loot_embed)

        # ── Quest mission advancement ──────────────────────────────────────────
        if session.state == CombatState.VICTORY and session.quest_mission_id:
            try:
                from cogs.quests import advance_quest, _load_quest as _lq, _mission_display_name
                q_profile = await persistence.load_player(session.user_id)
                status    = advance_quest(q_profile, session.quest_id, session.quest_mission_id)
                await persistence.save_player(q_profile)

                if status == "quest_complete":
                    qd    = _lq(session.quest_id)
                    qname = qd.get("name", session.quest_id) if qd else session.quest_id
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title=f"{E.lotus}  QUEST COMPLETE — {qname}",
                            description=(
                                "*\"Outstanding, Operator. This chapter is closed.\"*\n\n"
                                "Use `!quests` to check your Quest Log."
                            ),
                            color=0xC8A840,
                        )
                    )
                elif status == "advanced":
                    qd = _lq(session.quest_id)
                    if qd:
                        next_label = _mission_display_name(qd, q_profile.get("current_mission"))
                        await interaction.followup.send(
                            content=(
                                f"{E.lotus} *\"Mission complete, Operator. "
                                f"Next objective: **{next_label}**.\"*\n"
                                "Use `!mission` to continue."
                            )
                        )
            except Exception:
                import traceback
                traceback.print_exc()


def _disabled_view(session: CombatSession) -> "CombatView":
    view = CombatView(session)
    for child in view.children:
        child.disabled = True   # type: ignore[union-attr]
    return view


# ─────────────────────────────────────────────────────────────────────────────
# Row 0 — Primary attack + 4 ability buttons
# ─────────────────────────────────────────────────────────────────────────────

class BasicAttackButton(discord.ui.Button):
    """Fires the equipped Primary weapon — label and emoji come from WEAPON_STATS."""

    def __init__(self, session: CombatSession):
        wp       = WEAPON_STATS.get(session.primary_weapon_name, WEAPON_STATS["MK1-Braton"])
        wp_label = wp.get("action_label", session.primary_weapon_name)
        wp_emoji = wp["emoji"]

        disabled = (
            not session.is_player_turn
            or session.actions_remaining <= 0
            or session.is_over
        )
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=wp_label,
            emoji=wp_emoji,
            custom_id=f"combat_basic_{session.user_id}",
            row=0,
            disabled=disabled,
        )
        self.session = session

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return
        log = self.session.player_action(ability_index=None)
        await _refresh(interaction, self.session, log)


class AbilityButton(discord.ui.Button):
    """One of the four warframe abilities — label / emoji from _ABILITY_META."""

    def __init__(self, session: CombatSession, index: int):
        wf_key = session.player.warframe_key
        meta   = _ABILITY_META.get(wf_key, [])
        costs  = ABILITY_COSTS.get(wf_key, DEFAULT_ABILITY_COSTS)

        emoji, name = (
            meta[index] if index < len(meta)
            else (_NUMBER_EMOJIS[index], f"Ability {index + 1}")
        )
        cost = costs[index] if index < len(costs) else 0

        # Toggle abilities cost 0 to deactivate
        toggle_idx = TOGGLE_ABILITY_INDEX.get(wf_key)
        toggle_key = TOGGLE_FLAG_KEY.get(wf_key)
        if (
            toggle_idx is not None
            and index == toggle_idx
            and toggle_key is not None
            and session.player.ability_flags.get(toggle_key)
        ):
            cost = 0
            name = "Deactivate"

        disabled = (
            not session.is_player_turn
            or session.actions_remaining <= 0
            or session.player.energy < cost
            or session.is_over
            or session.tutorial
        )

        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=f"{name} ({cost})",
            emoji=emoji,
            custom_id=f"combat_ability_{index}_{session.user_id}",
            row=0,
            disabled=disabled,
        )
        self.session = session
        self.index   = index

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return
        log = self.session.player_action(ability_index=self.index)
        await _refresh(interaction, self.session, log)


# ─────────────────────────────────────────────────────────────────────────────
# Row 1 — End Turn, Melee, Secondary, Hold Cast*, Status
# ─────────────────────────────────────────────────────────────────────────────

class EndTurnButton(discord.ui.Button):
    def __init__(self, session: CombatSession):
        disabled = not session.is_player_turn or session.is_over
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="End Turn",
            emoji="🔚",
            custom_id=f"combat_endturn_{session.user_id}",
            row=1,
            disabled=disabled,
        )
        self.session = session

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return
        log = self.session.end_player_turn()
        await _refresh(interaction, self.session, log)


class MeleeButton(discord.ui.Button):
    """
    Melee weapon attack.
    Label / emoji come from WEAPON_STATS[session.melee_weapon_name] by default.
    If the warframe has an active toggle override (e.g. Excalibur's Exalted Blade),
    the label / emoji swap to the override defined in _MELEE_EXALTED_OVERRIDE.
    Finisher (×8 dmg) triggers automatically inside melee_attack() when the
    primary target is Blinded — no button-level special case needed.
    """

    def __init__(self, session: CombatSession):
        wp = WEAPON_STATS.get(session.melee_weapon_name, WEAPON_STATS["Skana"])

        disabled = (
            not session.is_player_turn
            or session.actions_remaining <= 0
            or session.is_over
        )

        # Check for warframe-specific toggle override (e.g. Exalted Blade)
        wf_key       = session.player.warframe_key
        override_flag = _MELEE_OVERRIDE_FLAG.get(wf_key)
        override_meta = _MELEE_EXALTED_OVERRIDE.get(wf_key)

        if (
            override_flag
            and override_meta
            and session.player.ability_flags.get(override_flag)
        ):
            emoji, label = override_meta
        else:
            label = wp.get("action_label", session.melee_weapon_name)
            emoji = wp["emoji"]

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label,
            emoji=emoji,
            custom_id=f"combat_melee_{session.user_id}",
            row=1,
            disabled=disabled,
        )
        self.session = session

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return
        log = self.session.player_melee()
        await _refresh(interaction, self.session, log)


class SecondaryButton(discord.ui.Button):
    """
    Secondary weapon attack.
    Label / emoji come from WEAPON_STATS[session.secondary_weapon_name].
    Swap the secondary weapon in CombatSession to see a different button automatically.
    """

    def __init__(self, session: CombatSession):
        wp = WEAPON_STATS.get(session.secondary_weapon_name, WEAPON_STATS["Lato"])

        disabled = (
            not session.is_player_turn
            or session.actions_remaining <= 0
            or session.is_over
        )
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=wp.get("action_label", session.secondary_weapon_name),
            emoji=wp["emoji"],
            custom_id=f"combat_secondary_{session.user_id}",
            row=1,
            disabled=disabled,
        )
        self.session = session

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return
        log = self.session.player_secondary()
        await _refresh(interaction, self.session, log)


class HoldCastButton(discord.ui.Button):
    """
    Hold-cast variant of an ability.
    All data (emoji, label, ability index, cost) comes from _HOLD_CAST_META
    and ABILITY_COSTS — no per-warframe hardcoding here.
    """

    def __init__(self, session: CombatSession):
        wf_key = session.player.warframe_key
        meta   = _HOLD_CAST_META.get(wf_key, (E.magnetize, "Hold Cast", 1))
        emoji, label, self._ability_index = meta

        costs = ABILITY_COSTS.get(wf_key, DEFAULT_ABILITY_COSTS)
        cost  = costs[self._ability_index] if self._ability_index < len(costs) else 0

        disabled = (
            not session.is_player_turn
            or session.actions_remaining <= 0
            or session.player.energy < cost
            or session.is_over
            or session.tutorial
        )
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=f"{label} ({cost})",
            emoji=emoji,
            custom_id=f"combat_hold_{session.user_id}",
            row=1,
            disabled=disabled,
        )
        self.session = session

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return
        log = self.session.player_action(ability_index=self._ability_index, hold=True)
        await _refresh(interaction, self.session, log)


class StatusButton(discord.ui.Button):
    """Shows a brief status summary as an ephemeral message — no action consumed."""

    def __init__(self, session: CombatSession):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Status",
            emoji="📊",
            custom_id=f"combat_status_{session.user_id}",
            row=1,
            disabled=session.is_over,
        )
        self.session = session

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return

        s   = self.session
        p   = s.player

        # Pull weapon emojis dynamically
        pw = WEAPON_STATS.get(s.primary_weapon_name, {})
        mw = WEAPON_STATS.get(s.melee_weapon_name,   {})
        sw = WEAPON_STATS.get(s.secondary_weapon_name, {})

        lines = [
            f"**{p.name}**",
            (
                f"{pw.get('emoji', '')} **{s.primary_weapon_name}**  ·  "
                f"{sw.get('emoji', '')} **{s.secondary_weapon_name}**  ·  "
                f"{mw.get('emoji', '')} **{s.melee_weapon_name}**"
            ),
            (
                f"<a:health:1499636458309423215> HP: {p.hp}/{p.max_hp}  "
                f"{E.shield} Shields: {p.shields}/{p.max_shields}"
            ),
            (
                f"<a:energy_orb:1499636329842212964> Energy: {p.energy}/{p.max_energy}  "
                f"{E.combo} Combo: {p.combo_gauge}"
            ),
            f"{E.lotus} Statuses: {p.status_icons()}",
            "",
        ]
        for enemy in s.enemies:
            if enemy.is_alive:
                lines.append(
                    f"{enemy.icon} **{enemy.name}** `[{enemy.faction}]` — "
                    f"HP {enemy.hp}/{enemy.max_hp}  "
                    f"Shields {enemy.shields}/{enemy.max_shields}  "
                    f"{enemy.status_icons()}"
                )
            else:
                lines.append(
                    f"~~{enemy.icon} {enemy.name}~~  {E.down}"
                )

        await interaction.response.send_message(
            "\n".join(lines), ephemeral=True
        )


# ─────────────────────────────────────────────────────────────────────────────
# View
# ─────────────────────────────────────────────────────────────────────────────

_OBJECTIVE_MODES = ("spy", "rescue", "sabotage", "mobile_defense")

_OBJECTIVE_META: dict[str, tuple[str, str]] = {
    "spy":            ("🔒", "Hack Console"),
    "rescue":         ("🔓", "Free Darvo"),
    "sabotage":       ("💣", "Sabotage"),
    "mobile_defense": ("📦", "Secure Cache"),
}


class ObjectiveButton(discord.ui.Button):
    """Context-sensitive mission-objective button (Row 2).

    Shown only for Spy / Rescue / Sabotage / Mobile Defense missions.
    Enabled only once all enemies are cleared and the objective is not yet done.
    """

    def __init__(self, session: CombatSession) -> None:
        mode               = session.game_mode
        emoji, label       = _OBJECTIVE_META.get(mode, ("🎯", "Objective"))
        enemies_cleared    = not session.living_enemies()
        can_act            = (
            session.is_player_turn
            and session.actions_remaining > 0
            and enemies_cleared
            and not session.objective_complete
            and not session.is_over
        )
        super().__init__(
            style     = discord.ButtonStyle.success,
            label     = label,
            emoji     = emoji,
            custom_id = f"combat_objective_{session.user_id}",
            row       = 2,
            disabled  = not can_act,
        )
        self.session = session

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message(
                "This is not your combat session, Tenno.", ephemeral=True
            )
            return
        log = self.session.player_objective()
        await _refresh(interaction, self.session, log)


class CombatView(discord.ui.View):
    """
    Full combat button panel.  Re-instantiated after every action so
    button disabled-states, labels, and emoji are always accurate.

    Row 0: [Primary Weapon]  [Ability 1]  [Ability 2]  [Ability 3]  [Ability 4]
    Row 1: [End Turn]  [Melee Weapon]  [Secondary Weapon]  [Hold Cast*]  [Status]
    Row 2: [Objective*]  (* only present for Spy / Rescue / Sabotage / MobDef)
           (* Hold Cast present only for warframes with HOLD_CAST_ABILITIES entries)

    All weapon button labels / emoji are read from WEAPON_STATS at construction
    time — adding a new weapon requires zero changes here.
    """

    def __init__(self, session: CombatSession):
        super().__init__(timeout=None)
        self.session = session

        # ── Row 0 ─────────────────────────────────────────────────────────────
        self.add_item(BasicAttackButton(session))
        for i in range(4):
            self.add_item(AbilityButton(session, i))

        # ── Row 1 ─────────────────────────────────────────────────────────────
        self.add_item(EndTurnButton(session))
        self.add_item(MeleeButton(session))
        self.add_item(SecondaryButton(session))
        if HOLD_CAST_ABILITIES.get(session.player.warframe_key):
            self.add_item(HoldCastButton(session))
        self.add_item(StatusButton(session))

        # ── Row 2 — objective (only for applicable game modes) ────────────────
        if session.game_mode in _OBJECTIVE_MODES:
            self.add_item(ObjectiveButton(session))


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class CombatCog(commands.Cog, name="Combat"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="abort", aliases=["retreat", "forfeit"])
    async def abort_cmd(self, ctx: commands.Context) -> None:
        """Abandon the current mission and clear your combat session."""
        session = ACTIVE_SESSIONS.pop(ctx.author.id, None)
        if session is None:
            await ctx.send("No active mission to abort, Tenno.", delete_after=6)
            return
        await ctx.send(
            "🚪 Mission aborted. The Lotus is disappointed, Operator.",
            delete_after=8,
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for session in ACTIVE_SESSIONS.values():
            self.bot.add_view(CombatView(session))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CombatCog(bot))
