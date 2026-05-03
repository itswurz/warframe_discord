# cogs/quests.py
# ─────────────────────────────────────────────────────────────────────────────
# Quest Log cog.
#
# Commands:
#   !quests / !quest          — Display the player's Quest Log
#   !quest start <id>         — Start a named quest by its ID
#   !mission / !deploy        — Deploy into the current quest mission
#
# Quest data lives in data/quests/<quest_id>.json.
# The active quest, mission, and completion tracking are stored in the player
# profile:  current_quest / current_mission / completed_quests / completed_missions
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import os

import discord
from discord.ext import commands

from data import persistence
from utils.emojis import E

QUESTS_DIR = "./data/quests"

_COLOR_DEFAULT = 0x1F4E5F
_COLOR_GOLD    = 0xC8A840


# ─────────────────────────────────────────────────────────────────────────────
# Quest data helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_quest(quest_id: str) -> dict | None:
    path = os.path.join(QUESTS_DIR, f"{quest_id}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _all_quest_ids() -> list[str]:
    try:
        return sorted(
            f[:-5] for f in os.listdir(QUESTS_DIR)
            if f.endswith(".json")
        )
    except Exception:
        return []


def _mission_display_name(quest: dict, mission_id: str | None) -> str:
    if not mission_id:
        return "—"
    for arc in quest.get("arcs", []):
        for m in arc.get("missions", []):
            if m["id"] == mission_id:
                return f"{m['name']}  ·  {m.get('location', '?')}"
    return mission_id


def _first_mission_id(quest: dict) -> str | None:
    for arc in quest.get("arcs", []):
        for m in arc.get("missions", []):
            return m["id"]
    return None


def _next_mission_id(quest: dict, current_mission_id: str) -> str | None:
    """Return the mission ID that follows current_mission_id, or None if it is last."""
    all_missions: list[str] = []
    for arc in quest.get("arcs", []):
        for m in arc.get("missions", []):
            all_missions.append(m["id"])
    try:
        idx = all_missions.index(current_mission_id)
        return all_missions[idx + 1] if idx + 1 < len(all_missions) else None
    except ValueError:
        return None


def advance_quest(profile: dict, quest_id: str, mission_id: str) -> str:
    """Mark *mission_id* complete for *quest_id* and advance the pointer.

    Modifies *profile* in-place.  Caller must save the profile afterward.

    Returns:
        "advanced"       — moved to the next mission in the quest
        "quest_complete" — no more missions; quest added to completed_quests
        "no_quest_data"  — quest JSON not found (no change made)
    """
    quest = _load_quest(quest_id)
    if not quest:
        return "no_quest_data"

    completed_missions: list = profile.setdefault("completed_missions", [])
    if mission_id not in completed_missions:
        completed_missions.append(mission_id)

    next_id = _next_mission_id(quest, mission_id)
    if next_id:
        profile["current_mission"] = next_id
        return "advanced"

    completed_quests: list = profile.setdefault("completed_quests", [])
    if quest_id not in completed_quests:
        completed_quests.append(quest_id)
    profile["current_quest"]   = None
    profile["current_mission"] = None
    return "quest_complete"


# ─────────────────────────────────────────────────────────────────────────────
# Embed builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_quest_log_embed(profile: dict) -> discord.Embed:
    current_quest_id   = profile.get("current_quest")
    current_mission_id = profile.get("current_mission")
    completed          = profile.get("completed_quests",   [])
    completed_missions = profile.get("completed_missions", [])

    embed = discord.Embed(
        title=f"{E.lotus}  QUEST LOG",
        color=_COLOR_DEFAULT,
    )
    embed.set_author(name="The Lotus  ·  Navigation Terminal")

    # ── Active quest ──────────────────────────────────────────────────────────
    if current_quest_id:
        quest = _load_quest(current_quest_id)
        if quest:
            quest_name  = quest.get("name", current_quest_id)
            faction     = quest.get("faction", "Unknown")
            description = quest.get("description", "—")

            # Per-arc mission progress
            progress_lines: list[str] = []
            for arc in quest.get("arcs", []):
                arc_name = arc.get("name", arc.get("id", "?"))
                progress_lines.append(f"**{arc_name}**")
                for m in arc.get("missions", []):
                    mid  = m["id"]
                    name = m["name"]
                    loc  = m.get("location", "?")
                    if mid in completed_missions:
                        progress_lines.append(f"  ✅ ~~{name}~~  ·  {loc}")
                    elif mid == current_mission_id:
                        progress_lines.append(f"  🎯 **{name}**  ·  {loc}  ← Current")
                    else:
                        progress_lines.append(f"  ⬜ {name}  ·  {loc}")

            progress_text = "\n".join(progress_lines) if progress_lines else "—"

            embed.add_field(
                name=f"ACTIVE — {quest_name}  (`{current_quest_id}`)",
                value=(
                    f"Faction: `{faction}`\n"
                    f"*{description}*\n\n"
                    f"{progress_text}\n\n"
                    f"Use `!mission` to deploy into your current objective."
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="ACTIVE QUEST",
                value=f"`{current_quest_id}` *(quest data not found)*",
                inline=False,
            )
    else:
        embed.add_field(
            name="ACTIVE QUEST",
            value=(
                "*No active quest, Operator.*\n"
                "Use `!quest start <id>` to begin one."
            ),
            inline=False,
        )

    # ── Completed quests ──────────────────────────────────────────────────────
    if completed:
        lines = []
        for qid in completed:
            q    = _load_quest(qid)
            name = q.get("name", qid) if q else qid
            lines.append(f"✅ **{name}**  (`{qid}`)")
        embed.add_field(
            name="COMPLETED",
            value="\n".join(lines),
            inline=False,
        )
    else:
        embed.add_field(name="COMPLETED", value="*None yet.*", inline=False)

    # ── Available quests (not active, not completed) ──────────────────────────
    all_ids   = _all_quest_ids()
    available = [
        qid for qid in all_ids
        if qid != current_quest_id and qid not in completed
    ]
    if available:
        lines = []
        for qid in available:
            q    = _load_quest(qid)
            name = q.get("name", qid) if q else qid
            lines.append(f"📋 **{name}**  (`{qid}`) — `!quest start {qid}`")
        embed.add_field(
            name="AVAILABLE",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(
        text="!mission to deploy  ·  !quest start <id> to begin  ·  Warframe © Digital Extremes"
    )
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class QuestsCog(commands.Cog, name="Quests"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── !quests / !quest ──────────────────────────────────────────────────────

    @commands.group(
        name="quest",
        aliases=["quests", "q"],
        invoke_without_command=True,
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def quest_cmd(self, ctx: commands.Context) -> None:
        """Display your Quest Log."""
        profile = await persistence.load_player(ctx.author.id)
        embed   = _build_quest_log_embed(profile)
        await ctx.send(
            content=f"{E.lotus} *\"The Navigation Terminal is ready, Operator.\"*",
            embed=embed,
        )

    # ── !quest start <id> ─────────────────────────────────────────────────────

    @quest_cmd.command(name="start", aliases=["begin"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def quest_start(self, ctx: commands.Context, quest_id: str) -> None:
        """Start a quest by its ID  (e.g. !quest start vors_prize)."""
        profile = await persistence.load_player(ctx.author.id)

        current = profile.get("current_quest")
        if current:
            q            = _load_quest(current)
            current_name = q.get("name", current) if q else current
            await ctx.send(
                f"{E.lotus} You already have an active quest: **{current_name}**.\n"
                "Complete it before starting another.",
                delete_after=12,
            )
            return

        if quest_id in profile.get("completed_quests", []):
            await ctx.send(
                f"{E.lotus} **{quest_id}** has already been completed, Operator.",
                delete_after=10,
            )
            return

        quest = _load_quest(quest_id)
        if quest is None:
            await ctx.send(
                f"{E.lotus} ❌ Quest `{quest_id}` was not found in the Navigation Terminal.\n"
                "Use `!quests` to see available quests.",
                delete_after=12,
            )
            return

        first_mission = _first_mission_id(quest)
        profile["current_quest"]   = quest_id
        profile["current_mission"] = first_mission
        await persistence.save_player(profile)

        embed = _build_quest_log_embed(profile)
        await ctx.send(
            content=(
                f"{E.lotus} "
                f"*\"Quest accepted, Operator. **{quest.get('name', quest_id)}** is now active.\"*"
            ),
            embed=embed,
        )

    # ── !mission ──────────────────────────────────────────────────────────────

    @commands.command(name="mission", aliases=["deploy"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def mission_cmd(self, ctx: commands.Context) -> None:
        """Deploy into your current quest mission."""
        from combat.session import CombatSession, ACTIVE_SESSIONS
        from combat.weapons import WEAPON_STATS
        from data.warframes import WARFRAMES
        from utils.combat_embeds import build_combat_embed
        from cogs.combat import CombatView

        profile = await persistence.load_player(ctx.author.id)

        current_quest_id   = profile.get("current_quest")
        current_mission_id = profile.get("current_mission")

        if not current_quest_id:
            await ctx.send(
                f"{E.lotus} *\"No active quest, Operator.\"*\n"
                "Use `!quests` to browse available quests.",
                delete_after=12,
            )
            return

        quest = _load_quest(current_quest_id)
        if not quest:
            await ctx.send(
                f"{E.lotus} ❌ Quest data for `{current_quest_id}` not found.",
                delete_after=10,
            )
            return

        # Find current mission data
        mission_data: dict | None = None
        for arc in quest.get("arcs", []):
            for m in arc.get("missions", []):
                if m["id"] == current_mission_id:
                    mission_data = m
                    break
            if mission_data:
                break

        if not mission_data:
            await ctx.send(
                f"{E.lotus} ❌ Mission `{current_mission_id}` not found in quest data.",
                delete_after=10,
            )
            return

        # Guard — already in an active session?
        existing = ACTIVE_SESSIONS.get(ctx.author.id)
        if existing and not existing.is_over:
            await ctx.send(
                "⚔️ You are already deployed, Tenno. "
                "Finish your current mission or use `!abort` first.",
                delete_after=8,
            )
            return
        ACTIVE_SESSIONS.pop(ctx.author.id, None)

        # Resolve loadout from profile
        wf_name = profile.get("warframe")
        if not wf_name:
            await ctx.send(
                f"{E.lotus} No Warframe equipped. Use `!warframe` to select one.",
                delete_after=10,
            )
            return

        wf_key = next(
            (k for k, v in WARFRAMES.items() if v["name"] == wf_name), None
        )
        if not wf_key:
            await ctx.send(
                f"{E.lotus} ❌ Warframe `{wf_name}` not found in the Codex.",
                delete_after=10,
            )
            return

        primary_name   = profile.get("weapon")           or "MK1-Braton"
        secondary_name = profile.get("secondary_weapon") or "Lato"
        melee_name     = profile.get("melee_weapon")     or "Skana"

        if primary_name   not in WEAPON_STATS: primary_name   = "MK1-Braton"
        if secondary_name not in WEAPON_STATS: secondary_name = "Lato"
        if melee_name     not in WEAPON_STATS: melee_name     = "Skana"

        session = CombatSession(
            warframe_key     = wf_key,
            warframe_data    = WARFRAMES[wf_key],
            user_id          = ctx.author.id,
            primary_weapon   = primary_name,
            secondary_weapon = secondary_name,
            melee_weapon     = melee_name,
            profile          = profile,
            quest_id         = current_quest_id,
            quest_mission_id = current_mission_id,
            game_mode        = mission_data.get("game_mode",    "exterminate"),
            mission_level    = mission_data.get("enemy_level",  1),
            quest_enemies    = mission_data.get("enemies",       None),
            mission_no_loot  = mission_data.get("no_loot",       False),
            no_die           = mission_data.get("no_die",         False),
        )
        ACTIVE_SESSIONS[ctx.author.id] = session

        pw = WEAPON_STATS.get(primary_name,   {})
        sw = WEAPON_STATS.get(secondary_name, {})
        mw = WEAPON_STATS.get(melee_name,     {})

        mission_name     = mission_data.get("name",     current_mission_id)
        mission_location = mission_data.get("location", "Unknown")

        embed = build_combat_embed(session, session.log[-10:])
        view  = CombatView(session)
        session._active_view = view

        await ctx.send(
            content=(
                f"{E.lotus} *\"Deploying to **{mission_name}**  ·  {mission_location}.\"*\n"
                f"{pw.get('emoji','')} **{primary_name}**  ·  "
                f"{sw.get('emoji','')} **{secondary_name}**  ·  "
                f"{mw.get('emoji','')} **{melee_name}**"
            ),
            embed=embed,
            view=view,
        )

    # ── Error handlers ────────────────────────────────────────────────────────

    @quest_cmd.error
    async def quest_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Navigation Terminal recalibrating. "
                f"Try again in `{error.retry_after:.1f}s`.",
                delete_after=6,
            )
        else:
            raise error

    @quest_start.error
    async def quest_start_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"{E.lotus} Please provide a quest ID.\n"
                "Usage: `!quest start <quest_id>`  e.g. `!quest start vors_prize`",
                delete_after=12,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Navigation Terminal recalibrating. "
                f"Try again in `{error.retry_after:.1f}s`.",
                delete_after=6,
            )
        else:
            raise error

    @mission_cmd.error
    async def mission_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Navigation Terminal recalibrating. "
                f"Try again in `{error.retry_after:.1f}s`.",
                delete_after=6,
            )
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuestsCog(bot))
