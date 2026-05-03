# cogs/quests.py
# ─────────────────────────────────────────────────────────────────────────────
# Quest Log cog.
#
# Commands:
#   !quests / !quest       — Display the player's Quest Log
#   !quest start <id>      — Start a named quest by its ID
#
# Quest data lives in data/quests/<quest_id>.json.
# The active quest and mission are tracked in the player profile via
# current_quest / current_mission fields.
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


# ─────────────────────────────────────────────────────────────────────────────
# Embed builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_quest_log_embed(profile: dict) -> discord.Embed:
    current_quest_id   = profile.get("current_quest")
    current_mission_id = profile.get("current_mission")
    completed          = profile.get("completed_quests", [])

    embed = discord.Embed(
        title=f"{E.lotus}  QUEST LOG",
        color=_COLOR_DEFAULT,
    )
    embed.set_author(name="The Lotus  ·  Navigation Terminal")

    # ── Active quest ──────────────────────────────────────────────────────────
    if current_quest_id:
        quest = _load_quest(current_quest_id)
        if quest:
            quest_name    = quest.get("name", current_quest_id)
            faction       = quest.get("faction", "Unknown")
            mission_label = _mission_display_name(quest, current_mission_id)
            description   = quest.get("description", "—")

            embed.add_field(
                name="ACTIVE QUEST",
                value=(
                    f"**{quest_name}**  ·  Faction: `{faction}`\n"
                    f"*{description}*\n\n"
                    f"{E.location} **Current Objective:** {mission_label}\n\n"
                    f"Use `!combat` to deploy into your current mission."
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
            lines.append(f"✅ **{name}**")
        embed.add_field(
            name="COMPLETED",
            value="\n".join(lines),
            inline=False,
        )
    else:
        embed.add_field(name="COMPLETED", value="*None yet.*", inline=False)

    # ── Available quests (not started, not completed) ─────────────────────────
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
            lines.append(f"📋 **{name}** — `!quest start {qid}`")
        embed.add_field(
            name="AVAILABLE",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(
        text="Quest Log  ·  !quest start <id> to begin  ·  Warframe © Digital Extremes"
    )
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class QuestsCog(commands.Cog, name="Quests"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuestsCog(bot))
