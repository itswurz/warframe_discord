# cogs/foundry.py
# ─────────────────────────────────────────────────────────────────────────────
# Warframe Foundry — time-based crafting system.
#
# Commands (prefix: !)
#   !foundry [category]  — browse all craftable items / filter by category
#   !craft  <item>       — start building; deducts materials immediately
#   !queue               — view active builds + completed builds ready to claim
#   !claim [item]        — claim a finished build, adds it to inventory/roster
#
# Data files:
#   data/foundry_recipes.json   — all item recipes (wiki-verified where noted)
#   data/foundry_emojis.json    — optional emoji overrides per item key
#   data/foundry_thumbnails.json— optional CDN thumbnail URLs per item key
#
# Queue entries stored inside player profile["foundry_queue"]:
#   {
#     "item_key":   str,
#     "item_name":  str,
#     "start_time": float,   # Unix timestamp
#     "finish_time":float,
#     "claimed":    bool,
#   }
#
# Design rules:
#   - Materials + credits deducted immediately on !craft
#   - Max MAX_QUEUE_SLOTS concurrent unclaimed builds per user
#   - Craft time = base_time + Σ(qty × rarity_weight) × 0.3, clamped [30, 900]
#   - All item data is JSON-driven — no hardcoded recipes in this file
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

from data import persistence
from utils.emojis import E

# ── Data file paths ────────────────────────────────────────────────────────────
_RECIPES_PATH = os.path.join("data", "foundry_recipes.json")
_THUMBS_PATH  = os.path.join("data", "foundry_thumbnails.json")

_PLACEHOLDER_IMG = "https://via.placeholder.com/128?text=No+Image"

MAX_QUEUE_SLOTS = 3


# ── JSON loaders ───────────────────────────────────────────────────────────────

def _load_json(path: str, fallback: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return fallback


RECIPES:    dict = _load_json(_RECIPES_PATH, {})
THUMBNAILS: dict = _load_json(_THUMBS_PATH,  {})

ITEMS:             dict = RECIPES.get("items",             {})
RESOURCE_RARITIES: dict = RECIPES.get("resource_rarities", {})
RARITY_WEIGHTS:    dict = RECIPES.get("rarity_weights",
                            {"common": 1, "uncommon": 2, "rare": 3, "legendary": 5})


# ── Emoji / thumbnail helpers ──────────────────────────────────────────────────

def _emoji(key: str) -> str:
    """Resolve item emoji via the central codex. Falls back to placeholder."""
    return E.item(key)


def _thumb(key: str) -> str:
    """Return thumbnail URL for key, falling back to placeholder. Never crashes."""
    return THUMBNAILS.get(key) or THUMBNAILS.get(key.lower().replace(" ", "_")) or _PLACEHOLDER_IMG


# ── Craft time formula ─────────────────────────────────────────────────────────

def _calc_craft_time(item_key: str) -> int:
    """
    final_craft_time = base_time + Σ(qty × rarity_weight) × 0.3
    Clamped to [30, 900] seconds (15 minutes max).
    Sub-components (other recipe keys) count as rarity-weight 3 (rare).
    """
    recipe     = ITEMS.get(item_key, {})
    base_time  = recipe.get("base_time", 60)
    multiplier = 0.3
    total_mat  = 0

    for ingredient, amount in recipe.get("ingredients", {}).items():
        if ingredient in ITEMS:
            weight = 3   # assembled component = rare-equivalent
        else:
            rarity = RESOURCE_RARITIES.get(ingredient, "common")
            weight = RARITY_WEIGHTS.get(rarity, 1)
        total_mat += amount * weight

    raw = base_time + int(total_mat * multiplier)
    return max(30, min(900, raw))


# ── Inventory / credit helpers ─────────────────────────────────────────────────

def _get_inv(profile: dict, name: str) -> int:
    return int(profile.get("inventory", {}).get(name, 0))


def _can_afford(profile: dict, item_key: str) -> tuple[bool, list[str]]:
    """
    Returns (can_craft, list_of_missing_lines).
    Checks both resource inventory and credits.
    """
    recipe  = ITEMS.get(item_key, {})
    missing = []

    for ingredient, needed in recipe.get("ingredients", {}).items():
        have = _get_inv(profile, ingredient)
        if have < needed:
            em    = _emoji(ingredient.lower().replace(" ", "_"))
            short = needed - have
            missing.append(
                f"{em} **{ingredient}**: need {needed:,}  ·  have {have:,}  (short **{short:,}**)"
            )

    credits_needed = recipe.get("credit_cost", 0)
    if credits_needed and profile.get("credits", 0) < credits_needed:
        short = credits_needed - profile.get("credits", 0)
        missing.append(
            f"💰 **Credits**: need {credits_needed:,}  ·  have {profile.get('credits',0):,}"
            f"  (short **{short:,}**)"
        )

    return (len(missing) == 0), missing


def _deduct_materials(profile: dict, item_key: str) -> None:
    """Consume ingredients + credits from profile. No safety check — call after _can_afford."""
    recipe = ITEMS.get(item_key, {})
    inv    = profile.setdefault("inventory", {})

    for ingredient, amount in recipe.get("ingredients", {}).items():
        inv[ingredient] = max(0, int(inv.get(ingredient, 0)) - amount)

    credit_cost = recipe.get("credit_cost", 0)
    if credit_cost:
        profile["credits"] = max(0, profile.get("credits", 0) - credit_cost)


# ── Queue helpers ──────────────────────────────────────────────────────────────

def _active_builds(profile: dict) -> list[dict]:
    return [e for e in profile.get("foundry_queue", []) if not e.get("claimed")]


def _ready_builds(profile: dict) -> list[dict]:
    now = time.time()
    return [
        e for e in _active_builds(profile)
        if e.get("finish_time", math.inf) <= now
    ]


def _fmt_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds <= 0:
        return "✅ Done!"
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s" if m else f"{s}s"


# ── Item lookup (fuzzy) ────────────────────────────────────────────────────────

def _find_item(query: str) -> Optional[str]:
    """
    Returns the first matching item_key for a user-supplied string.
    Tries: exact key → exact name → partial key/name.
    Returns None when nothing matches.
    """
    q = query.lower().strip()
    # 1. Exact key
    if q in ITEMS:
        return q
    # 2. Exact display name (case-insensitive)
    for key, data in ITEMS.items():
        if data.get("name", "").lower() == q:
            return key
    # 3. Partial match on key or name
    for key, data in ITEMS.items():
        if q in key or q in data.get("name", "").lower():
            return key
    return None


# ── Embed builders ─────────────────────────────────────────────────────────────

_COLORS = {
    "warframe":   0xC8A951,
    "component":  0x4A90D9,
    "weapon":     0xB03A2E,
}


def _color(item_type: str) -> int:
    return _COLORS.get(item_type, 0x4A90D9)


def _build_recipe_embed(item_key: str, profile: dict | None = None) -> discord.Embed:
    recipe     = ITEMS[item_key]
    name       = recipe["name"]
    itype      = recipe.get("type", "component")
    category   = recipe.get("category", itype)
    em         = _emoji(item_key)
    thumb      = _thumb(item_key)
    craft_secs = _calc_craft_time(item_key)

    embed = discord.Embed(
        title       = f"{em}  {name}",
        description = (
            f"**Type:** {itype.title()}  ·  **Category:** {category.replace('_',' ').title()}\n"
            f"⏱️ **Craft time:** `{_fmt_time(craft_secs)}`"
        ),
        color = _color(itype),
    )
    embed.set_thumbnail(url=thumb)

    # Ingredients
    lines = []
    for ingredient, amount in recipe.get("ingredients", {}).items():
        ie = _emoji(ingredient.lower().replace(" ", "_"))
        # Show player's current stock if profile provided
        if profile is not None:
            have  = _get_inv(profile, ingredient)
            color = "✅" if have >= amount else "❌"
            lines.append(f"{ie} **{ingredient}** × {amount:,}  {color} *(have {have:,})*")
        else:
            lines.append(f"{ie} **{ingredient}** × {amount:,}")

    credit_cost = recipe.get("credit_cost", 0)
    if credit_cost:
        if profile is not None:
            have  = profile.get("credits", 0)
            color = "✅" if have >= credit_cost else "❌"
            lines.append(f"💰 **Credits** × {credit_cost:,}  {color} *(have {have:,})*")
        else:
            lines.append(f"💰 **Credits** × {credit_cost:,}")

    embed.add_field(name="📋 Ingredients", value="\n".join(lines) or "—", inline=False)

    # Part-of indicator
    part_of = recipe.get("part_of")
    if part_of and part_of in ITEMS:
        parent_name = ITEMS[part_of]["name"]
        embed.add_field(
            name   = "🔗 Part Of",
            value  = f"{_emoji(part_of)} **{parent_name}**",
            inline = True,
        )

    wiki      = recipe.get("wiki_source", "")
    verified  = recipe.get("wiki_verified", False)
    unverified= recipe.get("_unverified_note", "")
    footer    = ""
    if wiki:
        tag    = "✅ Wiki-verified" if verified else "⚠️ Approximate (unverified)"
        footer = f"{tag}  ·  {wiki}"
        if unverified:
            footer += f"\n{unverified}"
    embed.set_footer(text=footer or "Use !craft <item> to build")
    return embed


_CATEGORY_LABELS = {
    "warframe":          "🏅 Warframes",
    "warframe_part":     "🔧 Warframe Components",
    "primary":           "🔫 Primary Weapons",
    "secondary":         "🔫 Secondary Weapons",
    "melee":             "⚔️  Melee Weapons",
    "sentinel":          "🤖 Sentinels",
    "craftable_resource":"⚗️  Craftable Resources",
    "other":             "📦 Other",
}

_FIELD_LIMIT = 1000   # Discord hard limit is 1024 — keep a small safety margin
_MAX_FIELDS  = 24     # Discord hard limit is 25 fields


def _add_chunked_fields(embed: discord.Embed, label: str, lines: list[str]) -> None:
    """Add lines as one or more fields, chunking at _FIELD_LIMIT chars."""
    chunk: list[str] = []
    current_len = 0
    part = 1

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > _FIELD_LIMIT and chunk:
            field_name = label if part == 1 else f"{label} (cont.)"
            embed.add_field(name=field_name, value="\n".join(chunk), inline=False)
            chunk = []
            current_len = 0
            part += 1
        chunk.append(line)
        current_len += line_len

    if chunk:
        field_name = label if part == 1 else f"{label} (cont.)"
        embed.add_field(name=field_name, value="\n".join(chunk), inline=False)


def _build_catalog_embed(category: str | None = None) -> discord.Embed:
    """
    No filter  → compact index showing each category with item count.
    With filter → full list for that category, chunked to respect Discord limits.
    """
    cat_filter = category.lower().strip() if category else None

    # Group items by category
    groups: dict[str, list[tuple[str, dict]]] = {}
    for key, data in ITEMS.items():
        cat = data.get("category", data.get("type", "other"))
        if cat_filter and cat_filter not in (cat, data.get("type", "")):
            continue
        groups.setdefault(cat, []).append((key, data))

    # ── No matching category ───────────────────────────────────────────────────
    if not groups:
        return discord.Embed(
            title       = "🏭 Foundry",
            description = f"No items found for category `{category}`.",
            color       = 0x2C2F33,
        )

    # ── No filter → show index ────────────────────────────────────────────────
    if not cat_filter:
        embed = discord.Embed(
            title = "🏭  FOUNDRY CATALOG",
            description = (
                "Filter by category to see recipes:\n\n"
                "`!foundry warframe`        — Warframe blueprints\n"
                "`!foundry warframe_part`   — Warframe components\n"
                "`!foundry primary`         — Primary weapons\n"
                "`!foundry secondary`       — Secondary weapons\n"
                "`!foundry melee`           — Melee weapons\n"
                "`!foundry sentinel`        — Sentinels\n"
                "`!foundry craftable_resource` — Craftable resources\n\n"
                "Or look up a specific item: `!foundry <item name>`\n"
                "To build: `!craft <item name>`"
            ),
            color = 0x4A90D9,
        )
        summary_lines = []
        for cat, items_in_cat in sorted(groups.items()):
            label   = _CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
            v_count = sum(1 for _, d in items_in_cat if d.get("wiki_verified"))
            summary_lines.append(
                f"{label} — **{len(items_in_cat)}** items  *(✅ {v_count} verified)*"
            )
        embed.add_field(
            name  = "📋 Available Categories",
            value = "\n".join(summary_lines),
            inline= False,
        )
        embed.set_footer(text=f"Total craftable items: {len(ITEMS)}  ·  ✅ = wiki-verified")
        return embed

    # ── Category filter → full list ───────────────────────────────────────────
    embed = discord.Embed(
        title       = f"🏭  FOUNDRY — {cat_filter.replace('_',' ').upper()}",
        description = "Use `!craft <item name>` to build.  `!foundry <item>` for full recipe.",
        color       = 0x4A90D9,
    )

    for cat, items_in_cat in sorted(groups.items()):
        label = _CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
        lines = []
        for key, data in items_in_cat:
            em       = _emoji(key)
            secs     = _calc_craft_time(key)
            verified = "✅" if data.get("wiki_verified") else "⚠️"
            lines.append(
                f"{em} **{data['name']}** — ⏱ `{_fmt_time(secs)}`  {verified}"
            )
        _add_chunked_fields(embed, label, lines)
        if len(embed.fields) >= _MAX_FIELDS:
            break

    embed.set_footer(text="✅ = wiki-verified  ·  ⚠️ = approximate data")
    return embed


def _build_queue_embed(profile: dict) -> discord.Embed:
    queue = profile.get("foundry_queue", [])
    now   = time.time()
    active = [e for e in queue if not e.get("claimed")]

    embed = discord.Embed(
        title       = "🏭  FOUNDRY QUEUE",
        description = f"Active builds: **{len(active)}** / {MAX_QUEUE_SLOTS}",
        color       = 0x4A90D9,
    )

    in_progress = [e for e in active if e.get("finish_time", 0) > now]
    ready       = [e for e in active if e.get("finish_time", 0) <= now]

    if in_progress:
        lines = []
        for e in in_progress:
            em        = _emoji(e.get("item_key", ""))
            remaining = e["finish_time"] - now
            lines.append(f"{em} **{e['item_name']}**  —  ⏱ `{_fmt_time(remaining)}`")
        embed.add_field(name="⚙️ In Progress", value="\n".join(lines), inline=False)

    if ready:
        lines = []
        for e in ready:
            em = _emoji(e.get("item_key", ""))
            lines.append(f"{em} **{e['item_name']}**  —  ✅ **READY TO CLAIM**")
        embed.add_field(name="📦 Awaiting Claim", value="\n".join(lines), inline=False)

    claimed_recent = [e for e in queue if e.get("claimed")][-5:]
    if claimed_recent:
        lines = [f"❔ **{e['item_name']}**  ·  claimed" for e in claimed_recent]
        embed.add_field(name="✔️ Recently Claimed", value="\n".join(lines), inline=False)

    if not active and not claimed_recent:
        embed.description = "Your Foundry is idle. Use `!craft <item>` to start building."

    embed.set_footer(text="!claim — claim a ready build  ·  !foundry — browse recipes")
    return embed


# ── Cog ────────────────────────────────────────────────────────────────────────

class FoundryCog(commands.Cog, name="Foundry"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── !foundry ──────────────────────────────────────────────────────────────

    @commands.group(
        name="foundry",
        aliases=["forge", "craft_list", "recipes"],
        invoke_without_command=True,
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def foundry_cmd(self, ctx: commands.Context, *, category: str = "") -> None:
        """
        Browse the Foundry catalog.

          !foundry                   — show all items
          !foundry warframe          — Warframe blueprints
          !foundry warframe_part     — Warframe components
          !foundry primary           — primary weapons
          !foundry secondary         — secondary weapons
          !foundry melee             — melee weapons
          !foundry <item name>       — show a specific recipe
        """
        if category:
            # Check if it's an item name first
            item_key = _find_item(category)
            if item_key:
                profile = await persistence.load_player(ctx.author.id)
                embed   = _build_recipe_embed(item_key, profile)
                await ctx.send(embed=embed)
                return

        embed = _build_catalog_embed(category or None)
        await ctx.send(embed=embed)

    # ── !craft ────────────────────────────────────────────────────────────────

    @commands.command(name="craft")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def craft_cmd(self, ctx: commands.Context, *, item_query: str) -> None:
        """
        Start crafting an item.  Materials + credits are deducted immediately.

          !craft Braton
          !craft Excalibur Neuroptics
          !craft excalibur
        """
        profile  = await persistence.load_player(ctx.author.id)

        if not profile.get("initialized"):
            await ctx.send(
                "❌ You haven't started your Warframe journey yet.\n"
                "Use `!warframe` to begin the tutorial.",
                delete_after=10,
            )
            return

        # Resolve item key
        item_key = _find_item(item_query)
        if not item_key:
            await ctx.send(
                f"❌ Unknown item: **{item_query}**\n"
                "Use `!foundry` to see all available recipes.",
                delete_after=12,
            )
            return

        recipe = ITEMS[item_key]

        # Queue limit check
        active = _active_builds(profile)
        if len(active) >= MAX_QUEUE_SLOTS:
            await ctx.send(
                f"❌ Foundry queue is full ({MAX_QUEUE_SLOTS}/{MAX_QUEUE_SLOTS} slots).\n"
                "Use `!claim` to free up a slot.",
                delete_after=10,
            )
            return

        # Duplicate active build check
        for build in active:
            if build.get("item_key") == item_key:
                await ctx.send(
                    f"❌ **{recipe['name']}** is already being built.\n"
                    "Use `!queue` to check build progress.",
                    delete_after=10,
                )
                return

        # Material check
        can_craft, missing = _can_afford(profile, item_key)
        if not can_craft:
            embed = discord.Embed(
                title       = f"❌  Insufficient Materials — {recipe['name']}",
                description = "You are missing the following:\n\n" + "\n".join(missing),
                color       = 0x7B1515,
            )
            embed.set_footer(text="Farm resources and try again.")
            await ctx.send(embed=embed)
            return

        # Deduct materials
        _deduct_materials(profile, item_key)

        # Add to queue
        craft_secs = _calc_craft_time(item_key)
        now        = time.time()
        entry      = {
            "item_key":   item_key,
            "item_name":  recipe["name"],
            "start_time": now,
            "finish_time":now + craft_secs,
            "claimed":    False,
        }
        profile.setdefault("foundry_queue", []).append(entry)
        await persistence.save_player(profile)

        em    = _emoji(item_key)
        thumb = _thumb(item_key)
        embed = discord.Embed(
            title       = f"{em}  Crafting Started — {recipe['name']}",
            description = (
                f"⏱️ **Build time:** `{_fmt_time(craft_secs)}`\n"
                f"✅ Materials and credits have been deducted.\n\n"
                f"Use `!queue` to monitor progress.\n"
                f"Use `!claim` when the build is complete."
            ),
            color = _color(recipe.get("type", "component")),
        )
        embed.set_thumbnail(url=thumb)
        credit_cost = recipe.get("credit_cost", 0)
        embed.set_footer(
            text=(
                f"Queue: {len(active)+1}/{MAX_QUEUE_SLOTS} slots used"
                + (f"  ·  {credit_cost:,} credits spent" if credit_cost else "")
            )
        )
        await ctx.send(embed=embed)

    # ── !queue ────────────────────────────────────────────────────────────────

    @commands.command(name="queue", aliases=["builds", "fqueue"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def queue_cmd(self, ctx: commands.Context) -> None:
        """Show your active Foundry builds and anything ready to claim."""
        profile = await persistence.load_player(ctx.author.id)
        embed   = _build_queue_embed(profile)
        await ctx.send(embed=embed)

    # ── !claim ────────────────────────────────────────────────────────────────

    @commands.command(name="claim", aliases=["collect", "retrieve"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def claim_cmd(
        self,
        ctx:        commands.Context,
        *,
        item_query: str = "",
    ) -> None:
        """
        Claim a completed Foundry build.

          !claim                — claim the first item that's ready
          !claim Braton         — claim a specific item by name
        """
        profile = await persistence.load_player(ctx.author.id)
        now     = time.time()
        queue   = profile.setdefault("foundry_queue", [])
        ready   = [
            e for e in queue
            if not e.get("claimed") and e.get("finish_time", math.inf) <= now
        ]

        if not ready:
            # Check if anything is still building
            active = _active_builds(profile)
            if active:
                soonest = min(e["finish_time"] for e in active)
                remaining = soonest - now
                await ctx.send(
                    f"⏳ Nothing is ready yet.\n"
                    f"Soonest build finishes in `{_fmt_time(remaining)}`.",
                    delete_after=12,
                )
            else:
                await ctx.send(
                    "❌ No builds in progress.\n"
                    "Use `!craft <item>` to start building.",
                    delete_after=10,
                )
            return

        # Find specific item if query given
        target_entry = None
        if item_query:
            item_key = _find_item(item_query)
            if item_key:
                target_entry = next(
                    (e for e in ready if e.get("item_key") == item_key), None
                )
            if target_entry is None:
                # Try matching by name substring
                q_lower = item_query.lower()
                target_entry = next(
                    (e for e in ready if q_lower in e.get("item_name", "").lower()),
                    None,
                )
            if target_entry is None:
                await ctx.send(
                    f"❌ **{item_query}** is not ready to claim yet, or doesn't exist.\n"
                    "Use `!queue` to see your builds.",
                    delete_after=10,
                )
                return
        else:
            # Claim the first ready item
            target_entry = ready[0]

        # Mark as claimed
        for e in queue:
            if (
                e.get("item_key")   == target_entry["item_key"]
                and e.get("start_time") == target_entry["start_time"]
                and not e.get("claimed")
            ):
                e["claimed"] = True
                break

        # Grant the item to the player
        item_key  = target_entry["item_key"]
        item_name = target_entry["item_name"]
        recipe    = ITEMS.get(item_key, {})
        result_type = recipe.get("result_type", "component")

        granted_to = "inventory"
        if result_type == "warframe":
            # Add to warframe roster (if slot available)
            from data.persistence import make_warframe_instance, MAX_WARFRAME_SLOTS
            from data.warframes import WARFRAMES
            roster = profile.setdefault("warframe_roster", [])
            if len(roster) < MAX_WARFRAME_SLOTS:
                wf_key  = recipe.get("warframe_key", item_key)
                wf_data = WARFRAMES.get(wf_key, {})
                wf_name = wf_data.get("name", item_name)
                existing_ids = {w.get("instance_id") for w in roster}
                instance = make_warframe_instance(
                    warframe_key  = wf_key,
                    warframe_name = wf_name,
                    existing_ids  = existing_ids,
                    is_active     = False,
                )
                roster.append(instance)
                granted_to = f"warframe roster (slot {len(roster)})"
            else:
                # Roster full — add to inventory as item
                persistence.add_to_inventory(profile, item_name, 1)
                granted_to = "inventory (roster full)"
        else:
            persistence.add_to_inventory(profile, item_name, 1)

        await persistence.save_player(profile)

        em    = _emoji(item_key)
        thumb = _thumb(item_key)
        embed = discord.Embed(
            title       = f"{em}  Item Claimed — {item_name}",
            description = (
                f"✅ **{item_name}** has been added to your **{granted_to}**!\n\n"
                + (
                    f"Use `!warframe equip <ID>` to equip your new Warframe."
                    if result_type == "warframe" else
                    f"Check `!inventory` to view your items."
                )
            ),
            color = _color(recipe.get("type", "component")),
        )
        embed.set_thumbnail(url=thumb)
        remaining_ready = len(ready) - 1
        if remaining_ready > 0:
            embed.set_footer(text=f"{remaining_ready} more item(s) ready — use !claim again")
        else:
            embed.set_footer(text="All builds claimed.")
        await ctx.send(embed=embed)

    # ── Error handlers ────────────────────────────────────────────────────────

    @foundry_cmd.error
    async def foundry_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error

    @craft_cmd.error
    async def craft_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "❌ Specify an item to craft.\n"
                "Usage: `!craft <item name>`  e.g. `!craft Braton`",
                delete_after=10,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error

    @queue_cmd.error
    async def queue_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error

    @claim_cmd.error
    async def claim_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FoundryCog(bot))
