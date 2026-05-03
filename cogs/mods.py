# cogs/mods.py
# ─────────────────────────────────────────────────────────────────────────────
# !mods          — Browse your mod collection (stacked by name, paginated)
# !mods upgrade <mod_uuid>  — Upgrade a specific mod instance with Endo + Credits
# !mods view    <mod_uuid>  — Inspect any mod by UUID (cross-player)
#
# Fixes applied:
#   1. Removed content= kwarg from ctx.send(view=LayoutView) — Components v2
#      messages must not mix a top-level content string with a LayoutView.
#      The header text now lives inside the first Container.
#   2. Made UUID lookup case-insensitive as a safety net (stored UUIDs are
#      always uppercase, but defensive matching prevents silent mismatches).
#   3. Fixed UpgradeConfirmView custom_ids to be per-user so concurrent
#      upgrade confirmations from different players don't collide.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import math
import os
from typing import Optional

import discord
from discord.ext import commands

from data import persistence
from utils.emojis import E
from data.persistence import (
    load_player,
    save_player,
    find_mod_by_uuid,
    endo_cost_next_rank,
    credit_cost_next_rank,
)

# ── Codex data ────────────────────────────────────────────────────────────────
_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "warframes_mods.json")
_DB: dict | None = None


def _db() -> dict:
    global _DB
    if _DB is None:
        with open(_DB_PATH, "r", encoding="utf-8") as f:
            _DB = json.load(f)
    return _DB


def _get_codex_mod(name: str) -> Optional[dict]:
    name_l = name.lower()
    for m in _db()["mods"]:
        if m["name"].lower() == name_l:
            return m
    return None


# ── Item CDN map  (mod_name → Discord CDN image URL) ─────────────────────────
def _load_cdn_map() -> dict[str, str]:
    path = os.path.join(os.path.dirname(__file__), "..", "item_cdn.txt")
    cdn: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if " -> " not in line:
                    continue
                fname, url = line.split(" -> ", 1)
                cdn[fname.strip().lower()] = url.strip()
    except FileNotFoundError:
        pass
    return cdn

_CDN_MAP: dict[str, str] = _load_cdn_map()


def _mod_cdn_url(mod_name: str) -> Optional[str]:
    """Return the Discord CDN image URL for a mod, or None if unavailable."""
    key = mod_name.replace(" ", "") + "Mod.png"
    return _CDN_MAP.get(key.lower())


# ── Case-insensitive UUID helpers ──────────────────────────────────────────────

def _get_mod_by_uuid(profile: dict, mod_uuid: str) -> Optional[dict]:
    """Case-insensitive UUID lookup — guards against any historic casing quirks."""
    uuid_upper = mod_uuid.upper()
    for mod in profile.get("mod_collection", []):
        if mod.get("uuid", "").upper() == uuid_upper:
            return mod
    return None


# ── Display helpers ────────────────────────────────────────────────────────────

_RARITY_TAG = {"rare": "R", "uncommon": "U", "common": "C"}

PAGE_SIZE = 6  # mod groups per page


def _rank_bar(rank: int, max_rank: int, length: int = 10) -> str:
    if max_rank == 0:
        return "`——————` Unrankable"
    ratio  = rank / max_rank
    filled = round(ratio * length)
    return f"`{'█' * filled}{'░' * (length - filled)}` {rank}/{max_rank}"


def _stat_at_rank(codex_mod: dict, rank: int) -> dict:
    """
    Compute display-only scaled stat values at a given rank.
    Rank 0 returns empty dict — used for the upgrade-preview display so the
    progression (rank 0→1→2…) is clearly visible.
    For LIVE effect computation (warframe stat bonuses) see
    utils/mods_ui._stat_at_rank which uses max(1, rank).
    """
    if rank == 0:
        return {}
    scaling = codex_mod.get("rank_scaling", {})
    result  = {}
    for stat_key, scale_info in scaling.items():
        per_rank = scale_info.get("per_rank", 0)
        result[stat_key] = round(per_rank * rank, 2)
    if not result:
        result = dict(codex_mod.get("stats", {}))
    return result


def _fmt_stat(key: str, value: float) -> str:
    """Format a stat key/value into a human-readable string."""
    labels = {
        "health_percent":             f"+{value:.0f}% Health",
        "shields_percent":            f"+{value:.0f}% Shields",
        "armor_percent":              f"+{value:.0f}% Armor",
        "energy_percent":             f"+{value:.0f}% Energy",
        "ability_efficiency_percent": f"-{value:.0f}% Ability Cost",
        "puncture_resist_percent":    f"+{value:.0f}% Puncture Resist",
        "knockdown_chance_percent":   f"+{value:.0f}% KD Chance",
        "loot_bonus_percent":         f"+{value:.0f}% Loot Bonus",
        "electricity_store_percent":  f"+{value:.0f}% Arc Store",
    }
    return labels.get(key, f"+{value:.0f}% {key.replace('_', ' ').title()}")


def _endo_cost_at_rank(codex_mod: dict | None, from_rank: int, rarity: str) -> int:
    """
    Get Endo cost to go from `from_rank` to `from_rank+1`.
    Prefers the codex array; falls back to persistence formula.
    """
    if codex_mod:
        costs = codex_mod.get("endo_costs_per_rank", [])
        if 0 <= from_rank < len(costs):
            return costs[from_rank]
    max_rank = codex_mod.get("max_rank", 5) if codex_mod else 5
    return endo_cost_next_rank(from_rank, max_rank, rarity)


def _credit_cost_at_rank(codex_mod: dict | None, from_rank: int, rarity: str) -> int:
    """
    Get Credit cost to go from `from_rank` to `from_rank+1`.
    Prefers the codex array; falls back to persistence formula.
    """
    if codex_mod:
        costs = codex_mod.get("credit_costs_per_rank", [])
        if 0 <= from_rank < len(costs):
            return costs[from_rank]
    max_rank = codex_mod.get("max_rank", 5) if codex_mod else 5
    return credit_cost_next_rank(from_rank, max_rank, rarity)


# ── ContainerBuilder (Components v2) ──────────────────────────────────────────

class _CB:
    def __init__(self, **kw):
        self.items = []
        self.kw = kw

    def text(self, content: str):
        self.items.append(discord.ui.TextDisplay(content))
        return self

    def section(self, content: str, thumbnail_url: Optional[str] = None):
        """TextDisplay optionally pinned with a Thumbnail accessory (Components V2 Section)."""
        if thumbnail_url:
            self.items.append(discord.ui.Section(
                discord.ui.TextDisplay(content),
                accessory=discord.ui.Thumbnail(thumbnail_url),
            ))
        else:
            self.items.append(discord.ui.TextDisplay(content))
        return self

    def sep(self, visible: bool = True,
            spacing: discord.SeparatorSpacing = discord.SeparatorSpacing.small):
        self.items.append(discord.ui.Separator(visible=visible, spacing=spacing))
        return self

    def row(self, *components):
        self.items.append(discord.ui.ActionRow(*components))
        return self

    def build(self) -> discord.ui.Container:
        return discord.ui.Container(*self.items, **self.kw)


# ─────────────────────────────────────────────────────────────────────────────
# Mod collection stacking
# ─────────────────────────────────────────────────────────────────────────────

def _group_mods(mod_collection: list[dict]) -> list[dict]:
    """
    Group mod_collection by name.
    Returns list of group dicts sorted rare→uncommon→common then A-Z:
    {
      name, rarity, codex_mod, count,
      copies: [{uuid, rank, max_rank, equipped_on_warframe, acquired_at}]
    }
    """
    order = {"rare": 0, "uncommon": 1, "common": 2}
    groups: dict[str, dict] = {}

    for inst in mod_collection:
        name = inst["name"]
        if name not in groups:
            cm = _get_codex_mod(name)
            groups[name] = {
                "name":      name,
                "rarity":    inst.get("rarity", "common"),
                "codex_mod": cm,
                "count":     0,
                "copies":    [],
            }
        groups[name]["count"] += 1
        groups[name]["copies"].append({
            "uuid":                 inst["uuid"],
            "rank":                 inst.get("rank", 0),
            "max_rank":             inst.get("max_rank", 5),
            "equipped_on_warframe": inst.get("equipped_on_warframe"),
            "acquired_at":          inst.get("acquired_at", ""),
        })

    result = sorted(
        groups.values(),
        key=lambda g: (order.get(g["rarity"], 9), g["name"]),
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# !mods  (list view)
# ─────────────────────────────────────────────────────────────────────────────

def _build_mods_list_layout(
    user_id:      int,
    mod_groups:   list[dict],
    page:         int,
    endo_amount:  int,
    credits:      int,
    owner_name:   str = "",
) -> discord.ui.LayoutView:
    total_pages = max(1, math.ceil(len(mod_groups) / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    slice_ = mod_groups[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]

    total_mods   = sum(g["count"] for g in mod_groups)
    total_unique = len(mod_groups)

    # ── Header — Components v2 text lives INSIDE the container, not as content=
    owner_tag = f"**{owner_name}'s** " if owner_name else ""
    header = (
        _CB(accent_colour=0x1F4E5F)
        .text(
            f"{E.lotus}  {owner_tag}**Mod Collection**  ·  "
            f"Page {page + 1}/{total_pages}\n"
            f"**{total_mods}** total  ·  **{total_unique}** unique  ·  "
            f"{E.endo} **{endo_amount:,}** Endo  ·  "
            f"{E.credits} **{credits:,}** Credits"
        )
        .sep(visible=False)
    )

    # ── Mod entries ───────────────────────────────────────────────────────────
    lines: list[str] = []
    for g in slice_:
        cm    = g["codex_mod"]
        re    = E.rarity(g["rarity"])
        rtag  = _RARITY_TAG.get(g["rarity"], "?")
        icon  = E.mod(g["name"], g["rarity"])
        count = g["count"]

        # Show each copy's UUID + rank inline
        copy_parts = []
        for c in g["copies"]:
            eq_tag = " 🔧" if c["equipped_on_warframe"] else ""
            rk_tag = f" R{c['rank']}/{c['max_rank']}" if c["max_rank"] > 0 else ""
            copy_parts.append(f"`{c['uuid']}`{rk_tag}{eq_tag}")

        copies_str = "  ".join(copy_parts)

        # Stats at max rank for reference
        stat_str = ""
        if cm:
            cur_stats = _stat_at_rank(cm, cm.get("max_rank", 5))
            parts = [_fmt_stat(k, v) for k, v in cur_stats.items()]
            stat_str = f" — *{', '.join(parts[:2])} (max)*" if parts else ""

        lines.append(
            f"{icon} **{g['name']}** `[{rtag}]` ×{count}{stat_str}\n"
            f"  {copies_str}"
        )

    content = "\n\n".join(lines) if lines else "*No mods in collection yet.*"
    header.text(content)
    header.sep()

    # ── Tip ───────────────────────────────────────────────────────────────────
    header.text(
        "Use `!mods upgrade <UUID>` to rank up a mod with Endo + Credits.\n"
        "Use `!mods view <UUID>` to inspect any mod in detail.\n"
        "🔧 = equipped on a Warframe"
    )

    # ── Pagination buttons ────────────────────────────────────────────────────
    prev_btn = discord.ui.Button(
        style=discord.ButtonStyle.secondary, label="◀ Prev",
        custom_id=f"mods_list_prev_{user_id}", disabled=(page <= 0),
    )
    page_btn = discord.ui.Button(
        style=discord.ButtonStyle.secondary, label=f"{page + 1} / {total_pages}",
        custom_id=f"mods_list_page_{user_id}", disabled=True,
    )
    next_btn = discord.ui.Button(
        style=discord.ButtonStyle.secondary, label="Next ▶",
        custom_id=f"mods_list_next_{user_id}", disabled=(page >= total_pages - 1),
    )

    async def _prev(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        _profile = await load_player(user_id)
        _groups  = _group_mods(_profile.get("mod_collection", []))
        _endo    = _profile.get("inventory", {}).get("Endo", 0)
        _creds   = _profile.get("credits", 0)
        layout   = _build_mods_list_layout(user_id, _groups, page - 1, _endo, _creds)
        await interaction.response.edit_message(view=layout)

    async def _next(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        _profile = await load_player(user_id)
        _groups  = _group_mods(_profile.get("mod_collection", []))
        _endo    = _profile.get("inventory", {}).get("Endo", 0)
        _creds   = _profile.get("credits", 0)
        layout   = _build_mods_list_layout(user_id, _groups, page + 1, _endo, _creds)
        await interaction.response.edit_message(view=layout)

    prev_btn.callback = _prev
    next_btn.callback = _next

    header.row(prev_btn, page_btn, next_btn)

    layout = discord.ui.LayoutView()
    layout.add_item(header.build())
    return layout


# ─────────────────────────────────────────────────────────────────────────────
# !mods view  (detail card — cross-player)
# ─────────────────────────────────────────────────────────────────────────────

def _build_mod_view_layout(
    mod_inst:     dict,
    codex_mod:    Optional[dict],
    owner_name:   str,
    owner_id:     str,
    warframe_ctx: str,
    is_owner:     bool,
) -> discord.ui.LayoutView:
    name   = mod_inst["name"]
    rarity = mod_inst.get("rarity", "common")
    rank   = mod_inst.get("rank", 0)
    max_r  = mod_inst.get("max_rank", codex_mod.get("max_rank", 5) if codex_mod else 5)
    uuid   = mod_inst["uuid"]
    re_em  = E.rarity(rarity)
    rtag   = rarity.capitalize()
    icon   = E.mod(name, rarity)

    accent = {"rare": 0xD4AF37, "uncommon": 0x4B9CDB, "common": 0x888888}.get(rarity, 0x1F4E5F)

    rk_bar = _rank_bar(rank, max_r)

    # ── CDN thumbnail ──────────────────────────────────────────────────────────
    thumb_url = _mod_cdn_url(name)

    # ── Stats section ─────────────────────────────────────────────────────────
    # Use effective rank (max 1, rank) so rank-0 shows the base effect, not blank
    eff_rank = max(1, rank)

    if codex_mod:
        endo_needed   = _endo_cost_at_rank(codex_mod, rank, rarity) if rank < max_r else 0
        credit_needed = _credit_cost_at_rank(codex_mod, rank, rarity) if rank < max_r else 0

        cur_stats  = _stat_at_rank(codex_mod, eff_rank)
        next_stats = _stat_at_rank(codex_mod, rank + 1) if rank < max_r else {}

        cur_lines  = [_fmt_stat(k, v) for k, v in cur_stats.items()]
        if not cur_lines:
            cur_lines = [f"*{codex_mod.get('description', 'No rank_scaling in codex')}*"]
        next_lines = [_fmt_stat(k, v) for k, v in next_stats.items()] if next_stats else ["—"]

        rank_label = f"Rank {rank}" if rank > 0 else "Rank 0"
        stats_text = (
            f"**Current Stats ({rank_label}):**\n"
            + "\n".join(f"  • {s}" for s in cur_lines)
        )
        if rank < max_r:
            upgrade_cost_line = (
                f"\n\n{E.endo} `{endo_needed:,}` Endo  "
                f"{E.credits} `{credit_needed:,}` Credits"
            )
            stats_text += (
                f"\n\n**Next Rank ({rank + 1}):**\n"
                + "\n".join(f"  • {s}" for s in next_lines)
                + upgrade_cost_line
            )
        else:
            stats_text += "\n\n✅ **Max Rank reached!**"
    else:
        # Mod not in warframes_mods.json — weapon / stance / unknown category
        source    = mod_inst.get("source", "unknown")
        acquired  = mod_inst.get("acquired_at", "")[:10]
        tradeable = mod_inst.get("tradeable", True)
        stats_text = (
            f"**Category:** Weapon / Stance / Other *(not a Warframe mod)*\n"
            f"**Source:** {source}  ·  **Acquired:** {acquired}\n"
            f"**Tradeable:** {'Yes' if tradeable else 'No — currently equipped'}\n\n"
            f"*This mod is not in the Warframe mod codex. "
            f"Weapon mods are managed through `!weapon mods`.*"
        )

    # ── Header (with optional thumbnail) ─────────────────────────────────────
    header_text = (
        f"{icon} **{name}** — {re_em} {rtag}\n"
        f"{E.combo} **UUID:** `{uuid}`\n"
        f"{E.lotus} **Owner:** {owner_name} *(ID: {owner_id})*\n"
        f"{E.location} **Location:** {warframe_ctx}\n"
        f"{E.defense} **Rank:** {rk_bar}"
    )

    # ── Codex footer ──────────────────────────────────────────────────────────
    codex_text = ""
    if codex_mod:
        desc       = codex_mod.get("description", "")
        cat        = codex_mod.get("category", "?")
        pol        = codex_mod.get("polarity", "any").capitalize()
        drain_base = codex_mod.get("base_drain", "?")
        drain_max  = codex_mod.get("max_drain", "?")
        codex_text = (
            f"**Category:** {cat}  ·  **Polarity:** {pol}  ·  "
            f"**Drain:** {drain_base}→{drain_max}\n"
            f"*{desc}*"
        )

    upgrade_hint = ""
    if is_owner and codex_mod and rank < max_r:
        upgrade_hint = f"\nUse `!mods upgrade {uuid}` to rank up."

    cb = (
        _CB(accent_colour=accent)
        .section(header_text, thumb_url)   # thumbnail on the header when available
        .sep()
        .text(stats_text)
    )
    if codex_text:
        cb.sep(visible=False)
        cb.text(codex_text)
    if upgrade_hint:
        cb.sep(visible=False)
        cb.text(upgrade_hint)

    layout = discord.ui.LayoutView()
    layout.add_item(cb.build())
    return layout


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade embed helpers

_RARITY_COLOUR = {"rare": 0xD4AF37, "uncommon": 0x4B9CDB, "common": 0x888888}


def _upgrade_confirm_embed(
    name: str, icon: str, rarity: str, mod_uuid: str,
    cur_rank: int, max_rank: int,
    cur_str: str, next_str: str,
    endo_cost: int, credit_cost: int,
    endo_have: int, credits_have: int,
    cdn_url: Optional[str] = None,
) -> discord.Embed:
    can_endo    = endo_have >= endo_cost
    can_credits = credits_have >= credit_cost
    colour      = _RARITY_COLOUR.get(rarity, 0x1F4E5F)
    re_em       = E.rarity(rarity)

    em = discord.Embed(
        title=f"⬆️  Upgrade — {name}",
        description=f"{icon}  {re_em} **{rarity.capitalize()}**  ·  `{mod_uuid}`",
        colour=colour,
    )
    if cdn_url:
        em.set_thumbnail(url=cdn_url)

    em.add_field(
        name="Rank Progress",
        value=(
            f"**{cur_rank}** → **{cur_rank + 1}**  /  {max_rank}\n"
            f"{_rank_bar(cur_rank, max_rank)}"
        ),
        inline=False,
    )
    em.add_field(
        name=f"Current  (Rank {cur_rank})",
        value=cur_str or "—",
        inline=True,
    )
    em.add_field(
        name=f"⬆️  After  (Rank {cur_rank + 1})",
        value=next_str or "—",
        inline=True,
    )
    em.add_field(
        name=f"{E.endo}  Endo",
        value=f"Cost  `{endo_cost:,}`\nHave  `{endo_have:,}` {'✅' if can_endo else '❌'}",
        inline=True,
    )
    em.add_field(
        name=f"{E.credits}  Credits",
        value=f"Cost  `{credit_cost:,}`\nHave  `{credits_have:,}` {'✅' if can_credits else '❌'}",
        inline=True,
    )
    return em


def _upgrade_result_embed(
    name: str, icon: str, rarity: str, mod_uuid: str,
    new_rank: int, max_rank: int,
    stat_block: str,
    rem_endo: int, rem_credits: int,
    next_endo: int, next_credits: int,
    cdn_url: Optional[str] = None,
) -> discord.Embed:
    maxed  = new_rank >= max_rank
    colour = 0x00C851 if maxed else _RARITY_COLOUR.get(rarity, 0x1F4E5F)
    re_em  = E.rarity(rarity)

    em = discord.Embed(
        title=f"{'✅  MAX — ' if maxed else '⬆️  Upgraded — '}{name}",
        description=f"{icon}  {re_em} **{rarity.capitalize()}**  ·  `{mod_uuid}`",
        colour=colour,
    )
    if cdn_url:
        em.set_thumbnail(url=cdn_url)

    em.add_field(
        name="New Rank",
        value=(
            f"**{new_rank}**  /  {max_rank}\n"
            f"{_rank_bar(new_rank, max_rank)}"
        ),
        inline=False,
    )
    em.add_field(
        name=f"Stats at Rank {new_rank}",
        value=stat_block or "—",
        inline=False,
    )
    em.add_field(
        name=f"{E.endo}  Endo Remaining",
        value=f"`{rem_endo:,}`",
        inline=True,
    )
    em.add_field(
        name=f"{E.credits}  Credits Remaining",
        value=f"`{rem_credits:,}`",
        inline=True,
    )
    if not maxed:
        em.add_field(
            name="Next Upgrade Cost",
            value=f"{E.endo} `{next_endo:,}` Endo  ·  {E.credits} `{next_credits:,}` Credits",
            inline=False,
        )
    else:
        em.add_field(
            name="✨  Fully Upgraded",
            value="This mod has reached its maximum potential.",
            inline=False,
        )
    return em


# ─────────────────────────────────────────────────────────────────────────────
# !mods upgrade  (confirmation view)
# ─────────────────────────────────────────────────────────────────────────────

class UpgradeConfirmView(discord.ui.View):
    def __init__(
        self,
        owner_id:     int,
        mod_uuid:     str,
        mod_name:     str,
        mod_icon:     str,
        mod_rarity:   str,
        cur_rank:     int,
        max_rank:     int,
        endo_cost:    int,
        credit_cost:  int,
        endo_have:    int,
        credits_have: int,
    ) -> None:
        super().__init__(timeout=30)
        self.owner_id     = owner_id
        self.mod_uuid     = mod_uuid
        self.mod_name     = mod_name
        self.mod_icon     = mod_icon
        self.mod_rarity   = mod_rarity
        self.cur_rank     = cur_rank
        self.max_rank     = max_rank
        self.endo_cost    = endo_cost
        self.credit_cost  = credit_cost
        self.endo_have    = endo_have
        self.credits_have = credits_have

        # Per-user custom_ids prevent button conflicts between concurrent upgrades
        confirm_btn = discord.ui.Button(
            label="Confirm Upgrade",
            style=discord.ButtonStyle.success,
            emoji="⬆️",
            custom_id=f"mods_upgrade_confirm_{owner_id}",
        )
        cancel_btn = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            emoji="❌",
            custom_id=f"mods_upgrade_cancel_{owner_id}",
        )
        confirm_btn.callback = self._confirm_cb
        cancel_btn.callback  = self._cancel_cb
        self.add_item(confirm_btn)
        self.add_item(cancel_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This confirmation belongs to another Operator.", ephemeral=True
            )
            return False
        return True

    async def _confirm_cb(self, interaction: discord.Interaction) -> None:
        profile  = await load_player(self.owner_id)
        mod_inst = _get_mod_by_uuid(profile, self.mod_uuid)

        if mod_inst is None:
            await interaction.response.edit_message(
                content="❌ Mod not found in your collection.", view=None
            )
            self.stop()
            return

        cur_rank   = mod_inst.get("rank", 0)
        max_rank   = mod_inst.get("max_rank", self.max_rank)
        mod_rarity = mod_inst.get("rarity", "common")

        if cur_rank >= max_rank:
            await interaction.response.edit_message(
                content=f"✅ **{self.mod_name}** is already at max rank.", view=None
            )
            self.stop()
            return

        endo_have    = profile.get("inventory", {}).get("Endo", 0)
        credits_have = profile.get("credits", 0)
        cm           = _get_codex_mod(self.mod_name)
        endo_cost    = _endo_cost_at_rank(cm, cur_rank, mod_rarity)
        cred_cost    = _credit_cost_at_rank(cm, cur_rank, mod_rarity)

        if endo_have < endo_cost:
            err = discord.Embed(
                title="❌ Not Enough Endo",
                description=f"Need `{endo_cost:,}` — you have `{endo_have:,}`.",
                colour=0xE74C3C,
            )
            await interaction.response.edit_message(embed=err, view=None)
            self.stop()
            return

        if credits_have < cred_cost:
            err = discord.Embed(
                title=f"{E.credits} Not Enough Credits",
                description=f"Need `{cred_cost:,}` — you have `{credits_have:,}`.",
                colour=0xE74C3C,
            )
            await interaction.response.edit_message(embed=err, view=None)
            self.stop()
            return

        # Deduct Endo
        new_endo = endo_have - endo_cost
        if new_endo == 0:
            profile["inventory"].pop("Endo", None)
        else:
            profile["inventory"]["Endo"] = new_endo
        # Deduct Credits
        profile["credits"] = credits_have - cred_cost
        # Rank up
        mod_inst["rank"] = cur_rank + 1
        await save_player(profile)

        new_rank     = mod_inst["rank"]
        new_stats    = _stat_at_rank(cm, new_rank) if cm else {}
        stat_block   = "\n".join(_fmt_stat(k, v) for k, v in new_stats.items()) or "—"
        rem_endo     = profile.get("inventory", {}).get("Endo", 0)
        rem_credits  = profile.get("credits", 0)
        next_endo    = _endo_cost_at_rank(cm, new_rank, mod_rarity) if new_rank < max_rank else 0
        next_credits = _credit_cost_at_rank(cm, new_rank, mod_rarity) if new_rank < max_rank else 0

        result_em = _upgrade_result_embed(
            name         = self.mod_name,
            icon         = self.mod_icon,
            rarity       = mod_rarity,
            mod_uuid     = self.mod_uuid,
            new_rank     = new_rank,
            max_rank     = max_rank,
            stat_block   = stat_block,
            rem_endo     = rem_endo,
            rem_credits  = rem_credits,
            next_endo    = next_endo,
            next_credits = next_credits,
            cdn_url      = _mod_cdn_url(self.mod_name),
        )
        await interaction.response.edit_message(embed=result_em, view=None)
        self.stop()

    async def _cancel_cb(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Upgrade cancelled.", view=None)
        self.stop()

    async def on_timeout(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class ModsCog(commands.Cog, name="Mods"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── !mods / !mod (base — show collection) ─────────────────────────────────
    # "mod" alias added so both !mods and !mod work.

    @commands.group(
        name="mods",
        aliases=["mod", "modlist", "modcollection"],
        invoke_without_command=True,
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def mods_cmd(self, ctx: commands.Context) -> None:
        """Browse your mod collection, stacked by mod name with individual UUIDs.
        Also available as !modlist."""
        profile  = await load_player(ctx.author.id)
        groups   = _group_mods(profile.get("mod_collection", []))
        endo     = profile.get("inventory", {}).get("Endo", 0)
        credits_ = profile.get("credits", 0)

        layout = _build_mods_list_layout(
            user_id    = ctx.author.id,
            mod_groups = groups,
            page       = 0,
            endo_amount= endo,
            credits    = credits_,
            owner_name = ctx.author.display_name,
        )
        # ⚠️  Components v2 LayoutView must be sent with view= only — no content=
        await ctx.send(view=layout)

    # ── !mods upgrade / !mod upgrade <uuid> ───────────────────────────────────

    @mods_cmd.command(name="upgrade", aliases=["up", "rank"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def mods_upgrade(self, ctx: commands.Context, mod_uuid: str) -> None:
        """
        Upgrade a mod by its UUID using Endo + Credits from your inventory.

        Usage:
          !mods upgrade A9X4M2Q
        """
        mod_uuid = mod_uuid.strip().upper()
        profile  = await load_player(ctx.author.id)
        mod_inst = _get_mod_by_uuid(profile, mod_uuid)

        if mod_inst is None:
            await ctx.send(
                f"{E.lotus} ❌ Mod `{mod_uuid}` not found in **your** collection.\n"
                "Use `!mods` to browse your mods and find the UUID.",
                delete_after=12,
            )
            return

        name     = mod_inst["name"]
        cur_rank = mod_inst.get("rank", 0)
        max_rank = mod_inst.get("max_rank", 5)
        rarity   = mod_inst.get("rarity", "common")
        cm       = _get_codex_mod(name)
        icon     = E.mod(name, rarity)

        if cur_rank >= max_rank:
            cdn_url = _mod_cdn_url(name)
            re_em   = E.rarity(rarity)
            colour  = _RARITY_COLOUR.get(rarity, 0x1F4E5F)
            em = discord.Embed(
                title=f"✅  MAX — {name}",
                description=(
                    f"{icon}  {re_em} **{rarity.capitalize()}**  ·  `{mod_uuid}`\n"
                    f"Already at max rank **{max_rank}**."
                ),
                colour=0x00C851,
            )
            if cdn_url:
                em.set_thumbnail(url=cdn_url)
            em.add_field(
                name="Rank",
                value=f"**{max_rank}**  /  {max_rank}\n{_rank_bar(max_rank, max_rank)}",
                inline=False,
            )
            await ctx.send(embed=em, delete_after=12)
            return

        endo_have    = profile.get("inventory", {}).get("Endo", 0)
        credits_have = profile.get("credits", 0)
        endo_cost    = _endo_cost_at_rank(cm, cur_rank, rarity)
        credit_cost  = _credit_cost_at_rank(cm, cur_rank, rarity)

        if cm and cur_rank == 0:
            base_eff   = cm.get("base_effect", cm.get("description", "—"))
            cur_str    = f"*{base_eff}*\n*(base — already applied when equipped)*"
            r1_stats   = _stat_at_rank(cm, 1)
            next_stats = r1_stats
        elif cm:
            cur_stats  = _stat_at_rank(cm, cur_rank)
            next_stats = _stat_at_rank(cm, cur_rank + 1)
            cur_str    = "\n".join(_fmt_stat(k, v) for k, v in cur_stats.items()) or "—"
        else:
            cur_stats  = {}
            next_stats = {}
            cur_str    = "—"
        next_str = (
            "\n".join(_fmt_stat(k, v) for k, v in next_stats.items())
            if next_stats else "—"
        )

        can_endo    = endo_have >= endo_cost
        can_credits = credits_have >= credit_cost
        can_rank    = can_endo and can_credits
        cdn_url     = _mod_cdn_url(name)

        confirm_em = _upgrade_confirm_embed(
            name         = name,
            icon         = icon,
            rarity       = rarity,
            mod_uuid     = mod_uuid,
            cur_rank     = cur_rank,
            max_rank     = max_rank,
            cur_str      = cur_str,
            next_str     = next_str,
            endo_cost    = endo_cost,
            credit_cost  = credit_cost,
            endo_have    = endo_have,
            credits_have = credits_have,
            cdn_url      = cdn_url,
        )

        if not can_rank:
            missing_parts = []
            if not can_endo:
                missing_parts.append(f"`{endo_cost - endo_have:,}` more Endo")
            if not can_credits:
                missing_parts.append(f"`{credit_cost - credits_have:,}` more Credits")
            confirm_em.set_footer(text=f"❌ Cannot upgrade — need {' and '.join(missing_parts)}.")
            await ctx.send(embed=confirm_em, delete_after=20)
            return

        confirm_em.set_footer(text="⚠️ Confirm to spend Endo + Credits — 30 seconds to decide.")
        view = UpgradeConfirmView(
            owner_id     = ctx.author.id,
            mod_uuid     = mod_uuid,
            mod_name     = name,
            mod_icon     = icon,
            mod_rarity   = rarity,
            cur_rank     = cur_rank,
            max_rank     = max_rank,
            endo_cost    = endo_cost,
            credit_cost  = credit_cost,
            endo_have    = endo_have,
            credits_have = credits_have,
        )
        await ctx.send(embed=confirm_em, view=view)

    # ── !mods view / !mod view <uuid> ─────────────────────────────────────────

    @mods_cmd.command(name="view", aliases=["inspect", "info", "v"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def mods_view(self, ctx: commands.Context, mod_uuid: str) -> None:
        """
        Inspect any mod by UUID — shows owner, rank, current/next stats,
        upgrade costs, and which Warframe it is equipped on.

        Usage:
          !mods view A9X4M2Q
        """
        mod_uuid = mod_uuid.strip().upper()

        # Fast path — own collection (case-insensitive)
        profile      = await load_player(ctx.author.id)
        mod_inst     = _get_mod_by_uuid(profile, mod_uuid)
        is_owner     = True
        owner_id_str = str(ctx.author.id)
        owner_name   = ctx.author.display_name

        if mod_inst is None:
            # Cross-player search
            is_owner = False
            async with ctx.typing():
                owner_id_str, mod_inst = await find_mod_by_uuid(mod_uuid)

            if mod_inst is None:
                await ctx.send(
                    f"{E.lotus} ❌ No mod with UUID `{mod_uuid}` found "
                    f"in any Tenno's collection.\n"
                    f"Use `!mods` to see your mod UUIDs.",
                    delete_after=14,
                )
                return

            try:
                owner      = await self.bot.fetch_user(int(owner_id_str))
                owner_name = owner.display_name
                is_owner   = (owner.id == ctx.author.id)
            except Exception:
                owner_name = f"Unknown Operator (`{owner_id_str}`)"

        # Determine equipped warframe context
        eq_on  = mod_inst.get("equipped_on_warframe")
        wf_ctx = "Not equipped"
        if eq_on:
            try:
                target_profile = profile if is_owner else await load_player(int(owner_id_str))
                for wf in target_profile.get("warframe_roster", []):
                    if wf.get("instance_id") == eq_on:
                        wf_name    = wf["warframe_name"]
                        slot_label = ""
                        em         = wf.get("equipped_mods", {})
                        for s_key, s_data in em.items():
                            if s_data and s_data.get("mod_uuid", "").upper() == mod_uuid:
                                slot_label = f" slot {s_key}"
                                break
                        wf_ctx = f"Equipped on **{wf_name}** `[{eq_on}]`{slot_label}"
                        break
                else:
                    wf_ctx = f"Equipped on Warframe `[{eq_on}]`"
            except Exception:
                wf_ctx = f"Equipped on Warframe `[{eq_on}]`"

        cm = _get_codex_mod(mod_inst["name"])
        layout = _build_mod_view_layout(
            mod_inst     = mod_inst,
            codex_mod    = cm,
            owner_name   = owner_name,
            owner_id     = owner_id_str,
            warframe_ctx = wf_ctx,
            is_owner     = is_owner,
        )
        # Components v2 LayoutView — no content=
        await ctx.send(view=layout)

    # ── Error handlers ────────────────────────────────────────────────────────

    @mods_cmd.error
    async def mods_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        else:
            raise error

    @mods_upgrade.error
    async def upgrade_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"{E.lotus} Provide a mod UUID.\n"
                "Usage: `!mods upgrade A9X4M2Q`\n"
                "Use `!mods` to see your mod UUIDs.",
                delete_after=10,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error

    @mods_view.error
    async def view_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"{E.lotus} Provide a mod UUID.\n"
                "Usage: `!mods view A9X4M2Q`",
                delete_after=10,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModsCog(bot))
