# utils/polarity_embeds.py
# ─────────────────────────────────────────────────────────────────────────────
# Discord embed helpers for the polarity system.
#
# Public API:
#   polarity_legend_field(embed)                  → adds a reference footer field
#   slot_row(slot_polarities, equipped_names)     → compact inline field value
#   mod_drain_preview(mod_name, base_drain,
#                     slot_polarity)              → single-line cost preview
#   build_polarity_overview_embed(warframe_key)   → standalone codex embed
#   add_polarity_fields_to_warframe_embed(embed,
#                     warframe_key)               → mutates an existing embed
#   add_polarity_field_to_weapon_embed(embed,
#                     weapon_name)                → mutates an existing embed
#   add_polarity_field_to_mod_embed(embed,
#                     mod_name, base_drain,
#                     slot_polarity)              → mutates an existing embed
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from typing import Optional

from data.polarity import (
    emoji as pol_emoji,
    display as pol_display,
    adjusted_drain,
    polarity_tag,
    slots_display,
    warframe_slot_polarities,
    weapon_slot_polarities,
    mod_polarity,
    capacity_summary,
    ANY,
)

# ── Constants ──────────────────────────────────────────────────────────────────

_BASE_CAPACITY  = 30   # TB base mod capacity (simplified from real game's 60 + forma)
_COLOR_MATCH    = 0x1A7A3C   # green
_COLOR_NEUTRAL  = 0x1F4E5F   # default teal
_COLOR_MISMATCH = 0x7B1515   # red

_LEGEND = (
    "✅ **Match** — same polarity → drain ÷ 2\n"
    "⚪ **Neutral** — `any` slot or `any` mod → no change\n"
    "❌ **Mismatch** — different polarity → drain × 2"
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slot_grid(slot_polarities: list[str], equipped_names: list[str | None] | None = None) -> str:
    """
    Build a compact grid string showing each slot's polarity emoji and the
    mod name (if equipped).  Four slots per row for readability.

        <emoji> *(empty)*   <emoji> Serration   <emoji> *(empty)*   <emoji> *(empty)*
        <emoji> *(empty)*   <emoji> *(empty)*   <emoji> *(empty)*   <emoji> *(empty)*
    """
    equipped = equipped_names or [None] * len(slot_polarities)
    lines = []
    row   = []

    for i, pol in enumerate(slot_polarities):
        em   = pol_emoji(pol)
        name = equipped[i] if i < len(equipped) else None
        cell = f"{em} **{name}**" if name else f"{em} *(empty)*"
        row.append(cell)
        if len(row) == 4:
            lines.append("  ".join(row))
            row = []

    if row:
        lines.append("  ".join(row))

    return "\n".join(lines) if lines else "*(no slots)*"


def _capacity_bar(used: int, capacity: int, length: int = 10) -> str:
    ratio  = min(1.0, used / max(1, capacity))
    filled = round(ratio * length)
    bar    = "█" * filled + "░" * (length - filled)
    return f"`{bar}` **{used}/{capacity}**"


# ─────────────────────────────────────────────────────────────────────────────
# Single-line helpers (used when mutating other embeds)
# ─────────────────────────────────────────────────────────────────────────────

def mod_drain_preview(
    mod_name:      str,
    base_drain:    int,
    slot_polarity: str,
) -> str:
    """
    Return a single-line string showing the cost of equipping a mod in a slot.

        <:madurai:…> slot  ×  <:madurai:…> mod  →  ✅ Match  7 drain  *(base 14)*
    """
    mp      = mod_polarity(mod_name)
    adj     = adjusted_drain(base_drain, slot_polarity, mp)
    tag     = polarity_tag(slot_polarity, mp)
    sp_em   = pol_emoji(slot_polarity)
    mp_em   = pol_emoji(mp)

    change  = ""
    if adj < base_drain:
        change = f" *(saved {base_drain - adj})*"
    elif adj > base_drain:
        change = f" *(+{adj - base_drain} penalty)*"

    return (
        f"{sp_em} slot  ×  {mp_em} mod  →  {tag}  "
        f"**{adj} drain**{change}  *(base {base_drain})*"
    )


def slot_row(slot_polarities: list[str]) -> str:
    """Return a space-separated row of polarity emojis for a compact field."""
    return slots_display(slot_polarities)


# ─────────────────────────────────────────────────────────────────────────────
# Embed mutators — add polarity fields to existing embeds
# ─────────────────────────────────────────────────────────────────────────────

def add_polarity_fields_to_warframe_embed(
    embed:        discord.Embed,
    warframe_key: str,
    profile:      dict | None = None,
) -> None:
    """
    Add polarity slot fields to an existing Warframe detail embed.

    Adds three rows:
      • WARFRAME SLOTS  — 8 mod slots with their polarity emojis
      • MELEE SLOTS     — melee weapon's polarity slots (Skana default)
      • POLARITY LEGEND — short rule reference
    If profile is passed, equipped mod names are shown in the slot grid.
    """
    wf_slots    = warframe_slot_polarities(warframe_key)
    melee_slots = warframe_slot_polarities(warframe_key)   # uses warframe's melee config

    # Pull equipped mods from profile if available
    equipped_wf: list[str | None] = [None] * 8
    if profile:
        em = profile.get("equipped_mods", {})
        wf_keys = [k for k in em if k.startswith("warframe_")]
        for i, k in enumerate(sorted(wf_keys)):
            mod_uuid = em.get(k)
            if mod_uuid:
                found = next(
                    (m["name"] for m in profile.get("mod_collection", []) if m["uuid"] == mod_uuid),
                    None,
                )
                if found and i < 8:
                    equipped_wf[i] = found

    embed.add_field(
        name="WARFRAME MOD SLOTS",
        value=_slot_grid(wf_slots, equipped_wf),
        inline=False,
    )
    embed.add_field(
        name="POLARITY RULES",
        value=_LEGEND,
        inline=False,
    )


def add_polarity_field_to_weapon_embed(
    embed:       discord.Embed,
    weapon_name: str,
) -> None:
    """Add a compact polarity row to an existing weapon detail embed."""
    slots = weapon_slot_polarities(weapon_name)
    embed.add_field(
        name="MOD SLOTS",
        value=slot_row(slots),
        inline=True,
    )


def add_polarity_field_to_mod_embed(
    embed:         discord.Embed,
    mod_name:      str,
    base_drain:    int,
    slot_polarity: str | None = None,
) -> None:
    """
    Add a polarity field to an existing mod embed.

    If slot_polarity is provided, also shows the adjusted drain preview for
    that specific slot.
    """
    mp    = mod_polarity(mod_name)
    mp_em = pol_emoji(mp)

    lines = [f"**Polarity:** {mp_em} {mp.capitalize()}"]

    if slot_polarity:
        lines.append(mod_drain_preview(mod_name, base_drain, slot_polarity))

    embed.add_field(
        name="POLARITY",
        value="\n".join(lines),
        inline=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Standalone polarity overview embed
# ─────────────────────────────────────────────────────────────────────────────

def build_polarity_overview_embed(
    warframe_key:   str,
    warframe_name:  str,
    profile:        dict | None = None,
) -> discord.Embed:
    """
    Full standalone embed showing all polarity slots for a Warframe + its weapons.

    Sections:
      1. WARFRAME SLOTS (8)
      2. PRIMARY SLOTS  (8)
      3. SECONDARY SLOTS (6)
      4. MELEE SLOTS    (8)
      5. MOD CAPACITY (from profile's current equipped mods)
      6. POLARITY LEGEND
    """
    wf_slots  = warframe_slot_polarities(warframe_key)
    embed = discord.Embed(
        title=f"<:wf_lotus:1499651243101126816>  {warframe_name} — Polarity Slots",
        description=(
            "Each slot's polarity determines how much mod capacity a mod consumes.\n"
            "Match the polarity to **halve** the drain. Mismatch to **double** it."
        ),
        color=0x1F4E5F,
    )

    # ── Warframe slots ─────────────────────────────────────────────────────────
    equipped_wf: list[str | None] = [None] * 8
    if profile:
        em = profile.get("equipped_mods", {})
        wf_keys = sorted(k for k in em if k.startswith("warframe_"))
        for i, k in enumerate(wf_keys):
            uid = em.get(k)
            if uid:
                found = next(
                    (m["name"] for m in profile.get("mod_collection", []) if m["uuid"] == uid),
                    None,
                )
                if found and i < 8:
                    equipped_wf[i] = found

    embed.add_field(
        name="WARFRAME SLOTS",
        value=_slot_grid(wf_slots, equipped_wf),
        inline=False,
    )

    # ── Capacity bar ───────────────────────────────────────────────────────────
    if profile:
        em = profile.get("equipped_mods", {})
        mc = profile.get("mod_collection", [])
        wf_equipped = []
        for k in sorted(k for k in em if k.startswith("warframe_")):
            uid = em.get(k)
            if uid:
                mod = next((m for m in mc if m["uuid"] == uid), None)
                if mod:
                    # Use rank 0 drain as base — full rank tracking is future scope
                    wf_equipped.append((mod["name"], 4))
                    continue
            wf_equipped.append(("", 0))

        summary = capacity_summary(_BASE_CAPACITY, wf_slots, wf_equipped)
        bar_str = _capacity_bar(summary["used"], summary["capacity"])
        over_tag = "  ⚠️ *Over capacity!*" if summary["over"] else ""
        embed.add_field(
            name="MOD CAPACITY",
            value=f"{bar_str}{over_tag}",
            inline=False,
        )

    # ── Legend ─────────────────────────────────────────────────────────────────
    embed.add_field(name="POLARITY RULES", value=_LEGEND, inline=False)
    embed.set_footer(
        text="Use !polarity <warframe> to inspect slots  ·  Warframe © Digital Extremes"
    )
    return embed


def build_mod_polarity_line(mod_name: str) -> str:
    """
    Return a one-line polarity string suitable for embedding inside any mod field.
    e.g.  "<:madurai:…> Madurai"
    """
    mp = mod_polarity(mod_name)
    return f"{pol_emoji(mp)} {mp.capitalize()}"


# ─────────────────────────────────────────────────────────────────────────────
# Weapon polarity overview (compact — for weapon detail cards)
# ─────────────────────────────────────────────────────────────────────────────

def build_weapon_slots_line(weapon_name: str) -> str:
    """
    Return a compact single-line slot display for a weapon.
    e.g.  "<:madurai:…>  <:naramon:…>  <:any:…>  <:any:…>  <:any:…>  <:any:…>"
    """
    return slot_row(weapon_slot_polarities(weapon_name))
