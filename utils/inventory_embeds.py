# utils/inventory_embeds.py
# ─────────────────────────────────────────────────────────────────────────────
# Embed builders for the dynamic inventory viewer and item description viewer.
#
# build_inventory_embed(profile, items, page, total_pages, filter_label)
#   → discord.Embed  — the paginated inventory grid
#
# build_item_embed(item_name, item_data, category, profile)
#   → discord.Embed  — full detail card for one item
#
# Mods are STACKED BY NAME in the inventory:
#   - One row per unique mod name, showing total count + individual UUIDs/ranks.
#   - Use !mods to get the full stacked mod list with upgrade commands.
#   - Use !item <name> to get the full description card.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from typing import Optional

from data.polarity import emoji as pol_emoji, mod_polarity as get_mod_polarity

DEFAULT_COLOR   = 0x1F4E5F
MOD_COLOR       = 0x2B4A6B
RESOURCE_COLOR  = 0x1F4E5F
COSMETIC_COLOR  = 0x4B3468

# ── Rarity display ────────────────────────────────────────────────────────────
RARITY_EMOJIS: dict[str, str] = {
    "common":    "<:common:1499767200410636351>",
    "uncommon":  "<:uncommon:1499767231926636705>",
    "rare":      "<:rare:1499767261236297899>",
    "cosmetic":  "✦",
}

RARITY_COLORS: dict[str, int] = {
    "common":    0x888888,
    "uncommon":  0x4B9CDB,
    "rare":      0xD4AF37,
    "cosmetic":  0x9B59B6,
}

# Footer-safe rarity labels — embed footers do not render custom emoji.
RARITY_FOOTER_LABELS: dict[str, str] = {
    "common":   "▫ Common",
    "uncommon": "◈ Uncommon",
    "rare":     "★ Rare",
    "cosmetic": "✦ Cosmetic",
}

CATEGORY_ICONS: dict[str, str] = {
    "Warframe":  "<:wf_lotus:1499651243101126816>",
    "Rifle":     "<:braton:1499699815813218325>",
    "Pistol":    "<:lato:1499699965109207051>",
    "Shotgun":   "<:damage:1499651176419950622>",
    "Melee":     "<:skana:1499700067672526899>",
    "Stance":    "<:combo:1499663262520971326>",
}

PAGE_SIZE = 8   # items per inventory page


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rarity_emoji(rarity: str) -> str:
    return RARITY_EMOJIS.get(rarity.lower(), "📦")


def _rarity_color(rarity: str) -> int:
    return RARITY_COLORS.get(rarity.lower(), DEFAULT_COLOR)


def _category_icon(category: str) -> str:
    return CATEGORY_ICONS.get(category, "<:damage:1499651176419950622>")


def _mod_icon_from_db(name: str, item_db: dict, fallback_emoji: str) -> str:
    """Try to get a mod's thumbnail or icon from item_descriptions.json."""
    meta = item_db.get("mods", {}).get(name, {})
    return meta.get("thumbnail") or fallback_emoji


# ─────────────────────────────────────────────────────────────────────────────
# Inventory data builders (pure functions — no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def build_display_items(profile: dict, item_db: dict) -> list[dict]:
    """
    Build a flat list of display-ready item dicts from a player profile.
    Each dict has: name, emoji, category, rarity, count, detail

    Sources:
      • profile["inventory"]      → resources, endo, cosmetics (all str→int)
      • profile["mod_collection"] → list of UUID mod instances

    Mods are STACKED BY NAME — one entry per unique mod name, showing
    the total count and individual UUIDs with their ranks inline.
    """
    items: list[dict] = []
    mod_db      = item_db.get("mods", {})
    resource_db = item_db.get("resources", {})
    cosmetic_db = item_db.get("cosmetics", {})

    # ── Mods: stack by name, show all UUIDs and ranks ──────────────────────────
    # Build groups keyed by mod name
    mod_groups: dict[str, dict] = {}

    for instance in profile.get("mod_collection", []):
        name   = instance["name"]
        rarity = instance.get("rarity", "common")
        uuid   = instance["uuid"]
        rank   = instance.get("rank", 0)
        max_r  = instance.get("max_rank", 5)
        eq_on  = instance.get("equipped_on_warframe")

        if name not in mod_groups:
            mod_meta = mod_db.get(name, {})
            mod_groups[name] = {
                "rarity":   rarity,
                "category": mod_meta.get("category", ""),
                "copies":   [],
                "count":    0,
            }
        mod_groups[name]["count"] += 1
        mod_groups[name]["copies"].append({
            "uuid":  uuid,
            "rank":  rank,
            "max_r": max_r,
            "eq_on": eq_on,
        })

    for name, gdata in mod_groups.items():
        mod_meta = mod_db.get(name, {})
        rarity   = gdata["rarity"]
        re       = _rarity_emoji(rarity)
        cat_ico  = _category_icon(gdata["category"])
        count    = gdata["count"]

        # Build compact UUID list — each copy on its own segment
        copy_parts: list[str] = []
        for c in gdata["copies"]:
            eq_tag = " 🔧" if c["eq_on"] else ""
            if c["max_r"] > 0:
                rk_tag = f" R{c['rank']}/{c['max_r']}"
            else:
                rk_tag = ""
            copy_parts.append(f"`{c['uuid']}`{rk_tag}{eq_tag}")

        # Show max 4 UUIDs inline to avoid line overflow; note remainder
        display_copies = copy_parts[:4]
        remainder      = count - len(display_copies)
        copies_line    = "  ".join(display_copies)
        if remainder > 0:
            copies_line += f"  *+{remainder} more*"

        # Max-rank stat preview from item_descriptions if available
        effect_hint = ""
        if mod_meta:
            effect_hint = f" — *{mod_meta.get('max_effect', '')}*" if mod_meta.get("max_effect") else ""

        detail = (
            f"{re} {cat_ico} **{name}** ×{count}{effect_hint}\n"
            f"  {copies_line}"
        )

        items.append({
            "name":     name,
            "emoji":    re,
            "category": "mod",
            "rarity":   rarity,
            "count":    count,
            "detail":   detail,
        })

    # ── Inventory items (resources, endo, cosmetics) ──────────────────────────
    for name, amount in profile.get("inventory", {}).items():
        if amount <= 0:
            continue

        if name == "Endo":
            items.append({
                "name":     "Endo",
                "emoji":    "<:endo:1499750353002954792>",
                "category": "endo",
                "rarity":   "uncommon",
                "count":    amount,
                "detail":   (
                    f"<:endo:1499750353002954792> **Endo** ×{amount:,}\n"
                    f"  *Mod upgrade material*"
                ),
            })
        elif name in resource_db:
            meta = resource_db[name]
            items.append({
                "name":     name,
                "emoji":    meta.get("emoji", "📦"),
                "category": "resource",
                "rarity":   "common",
                "count":    amount,
                "detail":   (
                    f"{meta.get('emoji','📦')} **{name}** ×{amount:,}\n"
                    f"  *{meta.get('source','Unknown source')}*"
                ),
            })
        elif name in cosmetic_db:
            meta = cosmetic_db[name]
            items.append({
                "name":     name,
                "emoji":    meta.get("emoji", "✦"),
                "category": "cosmetic",
                "rarity":   "cosmetic",
                "count":    amount,
                "detail":   (
                    f"✦ {meta.get('emoji','✦')} **{name}** ×{amount:,}\n"
                    f"  *{meta.get('source','Unknown source')}*"
                ),
            })
        else:
            # Unknown item — classify as generic resource
            items.append({
                "name":     name,
                "emoji":    "📦",
                "category": "resource",
                "rarity":   "common",
                "count":    amount,
                "detail":   f"📦 **{name}** ×{amount:,}",
            })

    # Sort: mods first by rarity (rare→common), then resources, endo, cosmetics
    order     = {"rare": 0, "uncommon": 1, "common": 2, "cosmetic": 3}
    cat_order = {"mod": 0, "endo": 1, "resource": 2, "cosmetic": 3}
    items.sort(key=lambda x: (
        cat_order.get(x["category"], 9),
        order.get(x["rarity"], 9),
        x["name"],
    ))
    return items


def apply_filter(items: list[dict], filter_key: str) -> list[dict]:
    """Filter the flat item list by the user-selected category."""
    if filter_key == "all":
        return items
    if filter_key == "mods":
        return [i for i in items if i["category"] == "mod"]
    if filter_key == "mods_common":
        return [i for i in items if i["category"] == "mod" and i["rarity"] == "common"]
    if filter_key == "mods_uncommon":
        return [i for i in items if i["category"] == "mod" and i["rarity"] == "uncommon"]
    if filter_key == "mods_rare":
        return [i for i in items if i["category"] == "mod" and i["rarity"] == "rare"]
    if filter_key == "resources":
        return [i for i in items if i["category"] == "resource"]
    if filter_key == "endo":
        return [i for i in items if i["category"] == "endo"]
    if filter_key == "cosmetics":
        return [i for i in items if i["category"] == "cosmetic"]
    return items


FILTER_LABELS: dict[str, str] = {
    "all":          "All Items",
    "mods":         "All Mods",
    "mods_common":  "<:common:1499767200410636351> Common Mods",
    "mods_uncommon":"<:uncommon:1499767231926636705> Uncommon Mods",
    "mods_rare":    "<:rare:1499767261236297899> Rare Mods",
    "resources":    "Resources",
    "endo":         "Endo",
    "cosmetics":    "Cosmetics",
}


# ─────────────────────────────────────────────────────────────────────────────
# Inventory embed
# ─────────────────────────────────────────────────────────────────────────────

def build_inventory_embed(
    profile:     dict,
    items:       list[dict],   # already filtered
    page:        int,
    total_pages: int,
    filter_key:  str,
    owner_name:  str,
    is_self:     bool = True,
) -> discord.Embed:

    wf    = profile.get("warframe") or "No Warframe"
    cr    = profile.get("credits", 0)
    mr    = profile.get("mastery_rank", 0)
    label = FILTER_LABELS.get(filter_key, filter_key)

    # Count total mods as individual instances, not stacked groups
    total_mod_instances = sum(
        i["count"] for i in items if i["category"] == "mod"
    )

    whose = "Your" if is_self else f"{owner_name}'s"
    embed = discord.Embed(
        title=f"<:wf_lotus:1499651243101126816>  {whose} Inventory",
        description=(
            f"**{wf}**  ·  MR {mr}  ·  {cr:,} Credits\n"
            f"Filter: **{label}**  ·  Page {page}/{max(1, total_pages)}"
        ),
        color=DEFAULT_COLOR,
    )

    if not items:
        embed.add_field(
            name="Nothing here yet",
            value="*Complete missions to gather resources, mods, and cosmetics.*",
            inline=False,
        )
        embed.set_footer(
            text=(
                "Use !mods to view your full mod collection  ·  "
                "Use !item <name> to inspect any item  ·  Warframe © Digital Extremes"
            )
        )
        return embed

    start      = (page - 1) * PAGE_SIZE
    end        = start + PAGE_SIZE
    page_items = items[start:end]

    # Two-column layout — left col gets items 0–3, right col gets 4–7
    left  = page_items[:4]
    right = page_items[4:8]

    def format_col(col: list[dict]) -> str:
        return "\n".join(i["detail"] for i in col) or "—"

    embed.add_field(name="\u200b", value=format_col(left),  inline=True)
    if right:
        embed.add_field(name="\u200b", value=format_col(right), inline=True)

    total_unique = sum(1 for i in items if i["category"] == "mod")
    embed.set_footer(
        text=(
            f"{len(items)} unique item type(s)  ·  {total_mod_instances} mod instance(s)  ·  "
            f"!mods for full mod list  ·  !item <name> to inspect  ·  Warframe © Digital Extremes"
        )
    )
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Item description embeds
# ─────────────────────────────────────────────────────────────────────────────

def build_mod_embed(
    name:    str,
    meta:    dict,
    profile: Optional[dict] = None,
) -> discord.Embed:
    """Full detail card for a single mod from item_descriptions.json."""

    rarity    = _find_mod_rarity(name, profile)
    color     = _rarity_color(rarity)
    re        = _rarity_emoji(rarity)
    cat_ico   = _category_icon(meta.get("category", ""))
    category  = meta.get("category", "Unknown")
    is_stance = (category == "Stance")

    embed = discord.Embed(
        description=f"*{meta.get('description', 'No description available.')}*",
        color=color,
    )
    embed.set_author(
        name=(
            f"{name}  ·  "
            f"{'Stance Mod' if is_stance else category + ' Mod'}  ·  "
            f"{rarity.capitalize()}"
        )
    )

    thumb = meta.get("thumbnail")
    if thumb:
        embed.set_thumbnail(url=thumb)

    # ── Stats panel ───────────────────────────────────────────────────────────
    drain_str = (
        f"{meta.get('base_drain', '?')} → {meta.get('max_drain', '?')}"
        if meta.get("max_rank", 0) > 0
        else str(meta.get("base_drain", "?"))
    )
    rank_str = (
        f"0 – {meta.get('max_rank', 0)}"
        if meta.get("max_rank", 0) > 0
        else "No ranks (equip as-is)"
    )

    compat = meta.get("compatible_weapons", [])
    compat_str = ", ".join(compat) if compat else "See category"

    weapon_class = meta.get("weapon_class") or category
    if is_stance:
        weapon_class = f"Sword — {meta.get('stance_weapon', 'Various')}"

    # Resolve polarity from the engine (JSON-backed, emoji-aware)
    _mp    = get_mod_polarity(name)
    _mp_em = pol_emoji(_mp)

    stats_lines = (
        f"{cat_ico} **Category:** {category}\n"
        f"<:damage_reduction:1499651603945226260> **Weapon Class:** {weapon_class}\n"
        f"<a:energy_orb:1499636329842212964> **Polarity:** {_mp_em} {_mp.capitalize()}\n"
        f"<:damage:1499651176419950622> **Drain:** {drain_str}\n"
        f"<:combo:1499663262520971326> **Ranks:** {rank_str}\n"
        f"<:wf_lotus:1499651243101126816> **Compatible:** {compat_str}"
    )
    embed.add_field(name="MOD INFO", value=stats_lines, inline=True)

    # ── Effect panel ──────────────────────────────────────────────────────────
    effect_lines = (
        f"**Base (Rank 0):** {meta.get('base_effect','?')}\n"
        f"**Max (Rank {meta.get('max_rank',0)}):** {meta.get('max_effect','?')}"
    )
    embed.add_field(name="EFFECT", value=effect_lines, inline=True)

    # ── TB Adaptation ─────────────────────────────────────────────────────────
    embed.add_field(
        name="TURN-BASED ADAPTATION",
        value=meta.get("tb_effect", "*No TB data available yet.*"),
        inline=False,
    )

    # ── User's owned copies (stacked by name, show each UUID + rank) ──────────
    if profile is not None:
        owned = [
            inst for inst in profile.get("mod_collection", [])
            if inst["name"] == name
        ]

        if owned:
            uuid_lines: list[str] = []
            for inst in owned[:15]:
                eq_on    = inst.get("equipped_on_warframe")
                eq_tag   = " 🔧 *equipped*" if eq_on else ""
                rank_val = inst.get("rank", 0)
                max_r    = inst.get("max_rank", 5)
                rank_tag = f" R{rank_val}/{max_r}"
                uuid_lines.append(f"`{inst['uuid']}`{rank_tag}{eq_tag}")
            if len(owned) > 15:
                uuid_lines.append(f"*…and {len(owned) - 15} more — use `!mods` to see all*")

            embed.add_field(
                name=f"YOUR COPIES  ({len(owned)} owned)",
                value="\n".join(uuid_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="YOUR COPIES  (0 owned)",
                value=(
                    "*You don't own this mod yet.*\n"
                    "Complete missions to find it as an enemy drop."
                ),
                inline=False,
            )

    embed.set_footer(
        text=(
            f"{RARITY_FOOTER_LABELS.get(rarity.lower(), rarity.capitalize())} Mod  ·  "
            f"Drain: {drain_str}  ·  "
            f"Use !mods upgrade <UUID> to rank up  ·  Warframe © Digital Extremes"
        )
    )
    return embed


def build_resource_embed(
    name:    str,
    meta:    dict,
    profile: Optional[dict] = None,
) -> discord.Embed:
    """Full detail card for a resource or Endo."""
    emoji  = meta.get("emoji", "📦")
    color  = 0x2C4A34 if name == "Endo" else DEFAULT_COLOR
    amount = 0
    if profile:
        amount = profile.get("inventory", {}).get(name, 0)

    embed = discord.Embed(
        description=f"*{meta.get('description', 'No description available.')}*",
        color=color,
    )
    embed.set_author(name=f"{name}  ·  Resource")

    thumb = meta.get("thumbnail")
    if thumb:
        embed.set_thumbnail(url=thumb)

    info_lines = (
        f"**Source:** {meta.get('source', 'Various')}\n"
        f"**TB Use:** {meta.get('tb_use', 'See description.')}"
    )
    embed.add_field(name="DETAILS", value=info_lines, inline=False)

    if profile is not None:
        embed.add_field(
            name="YOUR STOCK",
            value=f"{emoji} **{name}** ×{amount:,}" if amount else "*None in inventory.*",
            inline=False,
        )

    embed.set_footer(text="Resource  ·  Warframe © Digital Extremes")
    return embed


def build_cosmetic_embed(
    name:    str,
    meta:    dict,
    profile: Optional[dict] = None,
) -> discord.Embed:
    """Full detail card for a cosmetic."""
    emoji  = meta.get("emoji", "✦")
    amount = 0
    if profile:
        amount = profile.get("inventory", {}).get(name, 0)

    embed = discord.Embed(
        description=f"*{meta.get('description', 'No description available.')}*",
        color=COSMETIC_COLOR,
    )
    embed.set_author(name=f"{name}  ·  Cosmetic")

    thumb = meta.get("thumbnail")
    if thumb:
        embed.set_thumbnail(url=thumb)

    info_lines = (
        f"**Source:** {meta.get('source', 'Various')}\n"
        f"**TB Use:** {meta.get('tb_use', 'Cosmetic item.')}"
    )
    embed.add_field(name="DETAILS", value=info_lines, inline=False)

    if profile is not None:
        embed.add_field(
            name="YOUR STOCK",
            value=f"{emoji} **{name}** ×{amount:,}" if amount else "*None in inventory.*",
            inline=False,
        )

    embed.set_footer(text="✦ Cosmetic  ·  Warframe © Digital Extremes")
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Smart router — pick the right embed builder for any item name
# ─────────────────────────────────────────────────────────────────────────────

def build_item_embed(
    name:    str,
    item_db: dict,
    profile: Optional[dict] = None,
) -> Optional[discord.Embed]:
    """
    Given any item name, find it in the DB and build the correct embed.
    Returns None if the item is not found.

    Lookup order: mods → resources → cosmetics.
    Case-insensitive (exact match first, then lowercased fallback).
    """
    # Exact match first
    for db_key, db_section in (
        ("mods",      item_db.get("mods", {})),
        ("resources", item_db.get("resources", {})),
        ("cosmetics", item_db.get("cosmetics", {})),
    ):
        if name in db_section:
            meta = db_section[name]
            if db_key == "mods":
                return build_mod_embed(name, meta, profile)
            if db_key == "resources":
                return build_resource_embed(name, meta, profile)
            return build_cosmetic_embed(name, meta, profile)

    # Case-insensitive fallback
    name_lower = name.lower()
    for db_key, db_section in (
        ("mods",      item_db.get("mods", {})),
        ("resources", item_db.get("resources", {})),
        ("cosmetics", item_db.get("cosmetics", {})),
    ):
        for key, meta in db_section.items():
            if key.lower() == name_lower:
                if db_key == "mods":
                    return build_mod_embed(key, meta, profile)
                if db_key == "resources":
                    return build_resource_embed(key, meta, profile)
                return build_cosmetic_embed(key, meta, profile)

    return None


def _find_mod_rarity(name: str, profile: Optional[dict]) -> str:
    """Look up rarity of a mod from the player's collection; fallback to common."""
    if profile:
        for inst in profile.get("mod_collection", []):
            if inst["name"] == name:
                return inst.get("rarity", "common")
    return "common"
