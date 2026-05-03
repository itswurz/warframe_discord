# cogs/upgrades.py
# ─────────────────────────────────────────────────────────────────────────────
# !warframe upgrades <warframe_id>
#
# Full modding UI using Discord.py Components v2 Containers.
# All data is loaded from warframes_mods.json — never hardcoded.
#
# UI Layout (Components v2, no legacy Views):
#   Container 1 — Header + Stats
#     TextDisplay: warframe name + calculated stats
#     TextDisplay: mod capacity bar
#     Separator
#     ActionRow: 8 slot buttons (slots 0-3)
#     ActionRow: 8 slot buttons (slots 4-7)   [if warframe has >4 slots]
#
#   Container 2 — Mod Selection
#     TextDisplay: "Select a mod to equip" + selected mod indicator
#     Separator
#     ActionRow: [Select Menu] (25 mods max, paginated)
#     ActionRow: [◀ Prev]  [Selected: <mod>]  [Next ▶]
#
# State (per user, in-memory):
#   session["warframe_id"]     — warframe key
#   session["equipped"]        — list of mod UUIDs or None, len = num slots
#   session["selected_uuid"]   — currently highlighted mod UUID or None
#   session["page"]            — 0-indexed page of the mod select menu
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import math
import os
from typing import Any

import discord
from discord.ext import commands

# ── Data loading ──────────────────────────────────────────────────────────────

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "warframes_mods.json")

_DB: dict | None = None

def _db() -> dict:
    global _DB
    if _DB is None:
        try:
            with open(_DATA_PATH, "r", encoding="utf-8") as f:
                _DB = json.load(f)
        except FileNotFoundError:
            # Fallback: try current directory
            alt = os.path.join(os.path.dirname(__file__), "warframes_mods.json")
            with open(alt, "r", encoding="utf-8") as f:
                _DB = json.load(f)
    return _DB


def _get_warframe(warframe_id: str) -> dict | None:
    return _db()["warframes"].get(warframe_id.lower())


def _get_mods_sorted() -> list[dict]:
    """Return all mods sorted rarest → most common."""
    order = {r: i for i, r in enumerate(_db().get("rarity_order", ["rare", "uncommon", "common"]))}
    return sorted(_db()["mods"], key=lambda m: order.get(m["rarity"], 99))


def _get_mod_by_uuid(uuid: str) -> dict | None:
    for m in _db()["mods"]:
        if m["uuid"] == uuid:
            return m
    return None


def _polarity_info(polarity: str) -> dict:
    return _db()["slot_polarities"].get(polarity, {"emoji": "◻", "display": polarity.capitalize()})


# ── Stat calculation ──────────────────────────────────────────────────────────

def _calculate_stats(warframe_id: str, equipped: list[str | None]) -> dict:
    """
    Apply all equipped mods to base stats and return final stats dict.
    Fully data-driven: reads 'stats' from each mod JSON entry.
    """
    wf = _get_warframe(warframe_id)
    if not wf:
        return {}

    base = dict(wf["base_stats"])
    final = dict(base)

    # Accumulate percentage bonuses
    bonus: dict[str, float] = {}

    for uuid in equipped:
        if uuid is None:
            continue
        mod = _get_mod_by_uuid(uuid)
        if not mod:
            continue
        for stat_key, value in mod.get("stats", {}).items():
            bonus[stat_key] = bonus.get(stat_key, 0) + value

    # Apply health / shield / armor / energy percent bonuses
    if "health_percent" in bonus:
        final["health"] = int(base["health"] * (1 + bonus["health_percent"] / 100))
    if "shields_percent" in bonus:
        final["shields"] = int(base["shields"] * (1 + bonus["shields_percent"] / 100))
    if "armor_percent" in bonus:
        final["armor"] = int(base["armor"] * (1 + bonus["armor_percent"] / 100))
    if "energy_percent" in bonus:
        final["energy"] = int(base["energy"] * (1 + bonus["energy_percent"] / 100))

    # Store ability efficiency separately (displayed as a modifier)
    if "ability_efficiency_percent" in bonus:
        final["ability_efficiency_bonus"] = int(bonus["ability_efficiency_percent"])
    if "puncture_resist_percent" in bonus:
        final["puncture_resist_bonus"] = int(bonus["puncture_resist_percent"])

    return final


# ── Capacity calculation ──────────────────────────────────────────────────────

def _calculate_capacity(warframe_id: str, equipped: list[str | None]) -> tuple[int, int]:
    """Return (used_capacity, max_capacity)."""
    wf = _get_warframe(warframe_id)
    if not wf:
        return 0, 30

    max_cap = wf.get("mod_capacity", 30)
    slots   = wf["mod_slots"]
    used    = 0

    for slot_def in slots:
        uuid = equipped[slot_def["index"]] if slot_def["index"] < len(equipped) else None
        if uuid is None:
            continue
        mod = _get_mod_by_uuid(uuid)
        if not mod:
            continue

        slot_pol = slot_def["polarity"]
        mod_pol  = mod.get("polarity", "any")
        drain    = mod.get("max_drain", 10)

        if slot_pol != "any" and mod_pol != "any" and slot_pol == mod_pol:
            drain = math.ceil(drain / 2)

        used += drain

    return used, max_cap


# ── Session state ─────────────────────────────────────────────────────────────

# {user_id: {"warframe_id": str, "equipped": [...], "selected_uuid": str|None, "page": int}}
_SESSIONS: dict[int, dict] = {}

def _get_session(user_id: int, warframe_id: str) -> dict:
    if user_id not in _SESSIONS or _SESSIONS[user_id]["warframe_id"] != warframe_id:
        wf = _get_warframe(warframe_id)
        num_slots = len(wf["mod_slots"]) if wf else 8
        _SESSIONS[user_id] = {
            "warframe_id": warframe_id,
            "equipped": [None] * num_slots,
            "selected_uuid": None,
            "page": 0,
        }
    return _SESSIONS[user_id]


# ── Container builder helper (from comptest.py pattern) ──────────────────────

class ContainerBuilder:
    def __init__(self, **container_kwargs):
        self.items = []
        self.container_kwargs = container_kwargs

    def add_text(self, content: str, *, id: int | None = None):
        self.items.append(discord.ui.TextDisplay(content, id=id))
        return self

    def add_separator(self, *, visible: bool = True,
                      spacing: discord.SeparatorSpacing = discord.SeparatorSpacing.small,
                      id: int | None = None):
        self.items.append(discord.ui.Separator(visible=visible, spacing=spacing, id=id))
        return self

    def add_action_row(self, *components, id: int | None = None):
        self.items.append(discord.ui.ActionRow(*components, id=id))
        return self

    def add_item(self, item):
        self.items.append(item)
        return self

    def build(self) -> discord.ui.Container:
        return discord.ui.Container(*self.items, **self.container_kwargs)


# ── Capacity bar ──────────────────────────────────────────────────────────────

def _capacity_bar(used: int, cap: int, length: int = 10) -> str:
    ratio  = min(1.0, used / max(1, cap))
    filled = round(ratio * length)
    bar    = "█" * filled + "░" * (length - filled)
    over   = "  ⚠️ **OVER CAPACITY!**" if used > cap else ""
    return f"`{bar}` **{used}/{cap}**{over}"


# ── Stats text ────────────────────────────────────────────────────────────────

def _stats_text(warframe_id: str, equipped: list[str | None]) -> str:
    s = _calculate_stats(warframe_id, equipped)
    if not s:
        return "*No stats available.*"

    lines = [
        f"<a:health:1499636458309423215> **HP** {s['health']}",
        f"<:wf_shield:1499636531755745280> **Shields** {s['shields']}",
        f"<:damage_reduction:1499651603945226260> **Armor** {s['armor']}",
        f"<a:energy_orb:1499636329842212964> **Energy** {s['energy']}",
    ]
    if s.get("ability_efficiency_bonus"):
        lines.append(f"<:streamlinemod:1499760906576461825> **Eff. Bonus** -{s['ability_efficiency_bonus']}% cost")
    if s.get("puncture_resist_bonus"):
        lines.append(f"<:puncture:1499594734421803060> **Puncture Resist** +{s['puncture_resist_bonus']}%")
    return "  ".join(lines)


# ── Slot button builder ───────────────────────────────────────────────────────

def _build_slot_button(
    slot_def: dict,
    equipped_uuid: str | None,
    session: dict,
) -> discord.ui.Button:
    """Build a single mod slot button. Style/label/emoji are entirely data-driven."""
    slot_idx  = slot_def["index"]
    slot_pol  = slot_def["polarity"]
    pol_info  = _polarity_info(slot_pol)
    has_mod   = equipped_uuid is not None
    mod       = _get_mod_by_uuid(equipped_uuid) if has_mod else None
    selected  = session["selected_uuid"]

    if has_mod and mod:
        # Polarity match indicator
        mod_pol = mod.get("polarity", "any")
        match   = (slot_pol != "any" and mod_pol != "any" and slot_pol == mod_pol)
        suffix  = " ✓" if match else ""
        label   = f"{mod['name'][:18]}{suffix}"
        emoji   = mod["icon"]
        style   = discord.ButtonStyle.success if match else discord.ButtonStyle.primary
    else:
        if slot_pol == "any":
            label = "Empty Slot"
            emoji = "<:any:1499939092811743242>"
        else:
            label = pol_info["display"]
            emoji = pol_info["emoji"]
        style = discord.ButtonStyle.secondary

    btn = discord.ui.Button(
        style    = style,
        label    = label,
        emoji    = emoji,
        custom_id= f"slot_{slot_idx}",
    )

    # Store context for callback
    btn._slot_idx     = slot_idx
    btn._slot_def     = slot_def
    btn._equipped_uuid = equipped_uuid
    btn._session      = session

    return btn


def _attach_slot_callback(btn: discord.ui.Button, user_id: int, warframe_id: str,
                           message_ref: "MessageRef") -> None:
    async def _slot_cb(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message(
                "This modding panel belongs to another Operator.", ephemeral=True
            )
            return

        sess      = _get_session(user_id, warframe_id)
        slot_idx  = btn._slot_idx
        selected  = sess["selected_uuid"]
        current   = sess["equipped"][slot_idx]

        if selected is None:
            # No mod selected → unequip if occupied
            if current is not None:
                sess["equipped"][slot_idx] = None
        else:
            # A mod is selected → equip / replace
            sess["equipped"][slot_idx] = selected
            sess["selected_uuid"] = None

        layout = _build_layout(user_id, warframe_id)
        await interaction.response.edit_message(view=layout)

    btn.callback = _slot_cb


# ── Mod select menu ───────────────────────────────────────────────────────────

PAGE_SIZE = 25

def _build_mod_select(session: dict, user_id: int, warframe_id: str) -> discord.ui.Select:
    all_mods  = _get_mods_sorted()
    page      = session["page"]
    start     = page * PAGE_SIZE
    end       = start + PAGE_SIZE
    page_mods = all_mods[start:end]

    options = []
    for m in page_mods:
        pol_info = _polarity_info(m.get("polarity", "any"))
        rarity_tag = {"rare": "[R]", "uncommon": "[U]", "common": "[C]"}.get(m["rarity"], "")
        options.append(discord.SelectOption(
            label       = f"{m['name']} {rarity_tag}",
            value       = m["uuid"],
            description = m.get("description", "")[:100],
            emoji       = m["icon"],
            default     = (session["selected_uuid"] == m["uuid"]),
        ))

    sel = discord.ui.Select(
        custom_id   = "mod_select",
        placeholder = "Choose a mod to equip…",
        min_values  = 1,
        max_values  = 1,
        options     = options,
    )

    async def _select_cb(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        sess = _get_session(user_id, warframe_id)
        sess["selected_uuid"] = sel.values[0]
        layout = _build_layout(user_id, warframe_id)
        await interaction.response.edit_message(view=layout)

    sel.callback = _select_cb
    return sel


def _build_pagination_buttons(session: dict, user_id: int, warframe_id: str) -> list[discord.ui.Button]:
    all_mods   = _get_mods_sorted()
    total_pages = math.ceil(len(all_mods) / PAGE_SIZE)
    page        = session["page"]
    selected    = session["selected_uuid"]

    # Prev button
    prev_btn = discord.ui.Button(
        style    = discord.ButtonStyle.secondary,
        label    = "◀ Prev",
        custom_id= "mod_prev",
        disabled = (page <= 0),
    )
    async def _prev(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        sess = _get_session(user_id, warframe_id)
        sess["page"] = max(0, sess["page"] - 1)
        await interaction.response.edit_message(view=_build_layout(user_id, warframe_id))
    prev_btn.callback = _prev

    # Selected indicator (disabled display button)
    if selected:
        mod = _get_mod_by_uuid(selected)
        ind_label = f"✅ {mod['name']}" if mod else "✅ Selected"
        ind_emoji = mod["icon"] if mod else None
    else:
        ind_label = "None Selected"
        ind_emoji = None

    ind_btn = discord.ui.Button(
        style    = discord.ButtonStyle.secondary,
        label    = ind_label[:80],
        custom_id= "mod_indicator",
        disabled = True,
    )
    if ind_emoji:
        ind_btn.emoji = ind_emoji

    # Next button
    next_btn = discord.ui.Button(
        style    = discord.ButtonStyle.secondary,
        label    = "Next ▶",
        custom_id= "mod_next",
        disabled = (page >= total_pages - 1),
    )
    async def _next(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        sess = _get_session(user_id, warframe_id)
        sess["page"] = min(total_pages - 1, sess["page"] + 1)
        await interaction.response.edit_message(view=_build_layout(user_id, warframe_id))
    next_btn.callback = _next

    # Clear selection button
    clear_btn = discord.ui.Button(
        style    = discord.ButtonStyle.danger,
        label    = "Clear Selection",
        custom_id= "mod_clear",
        emoji    = "✖️",
        disabled = (selected is None),
    )
    async def _clear(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        sess = _get_session(user_id, warframe_id)
        sess["selected_uuid"] = None
        await interaction.response.edit_message(view=_build_layout(user_id, warframe_id))
    clear_btn.callback = _clear

    return [prev_btn, ind_btn, next_btn, clear_btn]


# ── Main layout builder ───────────────────────────────────────────────────────

class MessageRef:
    """Placeholder to satisfy forward references; not used in practice."""
    pass

_RARITY_COLOR = {
    "rare":     0xD4AF37,
    "uncommon": 0x4B9CDB,
    "common":   0x888888,
}

def _build_layout(user_id: int, warframe_id: str) -> discord.ui.LayoutView:
    sess = _get_session(user_id, warframe_id)
    wf   = _get_warframe(warframe_id)
    if not wf:
        layout = discord.ui.LayoutView()
        err    = ContainerBuilder(accent_colour=0x7B1515)\
                   .add_text(f"❌ Warframe `{warframe_id}` not found.")\
                   .build()
        layout.add_item(err)
        return layout

    equipped     = sess["equipped"]
    used, max_cap = _calculate_capacity(warframe_id, equipped)
    stats_line   = _stats_text(warframe_id, equipped)
    cap_bar      = _capacity_bar(used, max_cap)
    slots        = wf["mod_slots"]

    # ── Accent colour: green if under cap, red if over ────────────────────────
    accent = 0x1A7A3C if used <= max_cap else 0x7B1515

    # ── Slot buttons ──────────────────────────────────────────────────────────
    slot_buttons: list[discord.ui.Button] = []
    for slot_def in slots:
        idx  = slot_def["index"]
        uuid = equipped[idx] if idx < len(equipped) else None
        btn  = _build_slot_button(slot_def, uuid, sess)
        _attach_slot_callback(btn, user_id, warframe_id, MessageRef())
        slot_buttons.append(btn)

    # Discord ActionRow max 5 buttons; split 8 slots into rows of 4
    row1 = slot_buttons[:4]
    row2 = slot_buttons[4:8]

    # ── Build header container ────────────────────────────────────────────────
    wf_name    = wf["name"]
    lotus_line = f"<:wf_lotus:1499651243101126816>  **{wf_name}** — Mod Configuration"

    header_builder = (
        ContainerBuilder(accent_colour=accent)
        .add_text(lotus_line)
        .add_text(stats_line)
        .add_separator(visible=False)
        .add_text(f"**Mod Capacity:** {cap_bar}")
        .add_separator()
    )
    if row1:
        header_builder.add_action_row(*row1)
    if row2:
        header_builder.add_action_row(*row2)

    header_container = header_builder.build()

    # ── Build mod selection container ─────────────────────────────────────────
    all_mods    = _get_mods_sorted()
    total_pages = max(1, math.ceil(len(all_mods) / PAGE_SIZE))
    page        = sess["page"]
    selected_uuid = sess["selected_uuid"]

    hint = (
        "*Click a slot to **equip** the selected mod, or **remove** the equipped one.*\n"
        "*Polarity match (✓) halves the capacity cost.*"
    )
    if selected_uuid:
        mod = _get_mod_by_uuid(selected_uuid)
        if mod:
            pol_info  = _polarity_info(mod.get("polarity", "any"))
            drain_val = mod.get("max_drain", "?")
            hint = (
                f"{mod['icon']} **{mod['name']}** selected  ·  "
                f"{pol_info['emoji']} {pol_info['display']}  ·  "
                f"Drain: **{drain_val}**\n"
                f"*{mod.get('description', '')}*\n\n"
                "*Click an empty or filled slot to equip / replace.*"
            )

    mod_select  = _build_mod_select(sess, user_id, warframe_id)
    pag_buttons = _build_pagination_buttons(sess, user_id, warframe_id)

    mod_builder = (
        ContainerBuilder(accent_colour=0x2B4A6B)
        .add_text(f"**Mod Selection**  ·  Page {page + 1}/{total_pages}")
        .add_text(hint)
        .add_separator(visible=False)
        .add_action_row(mod_select)
        .add_action_row(*pag_buttons)
    )
    mod_container = mod_builder.build()

    # ── Compose layout ────────────────────────────────────────────────────────
    layout = discord.ui.LayoutView()
    layout.add_item(header_container)
    layout.add_item(mod_container)
    return layout


# ── Cog ───────────────────────────────────────────────────────────────────────

class UpgradesCog(commands.Cog, name="Upgrades"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name="upgrades", invoke_without_command=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def upgrades_cmd(self, ctx: commands.Context, warframe_id: str | None = None) -> None:
        """
        Open the Warframe mod configuration panel.

        Usage:
          !warframe upgrades excalibur
          !warframe upgrades mag
          !warframe upgrades volt
        """
        # Resolve warframe_id from argument or profile
        if not warframe_id:
            from data import persistence
            profile = await persistence.load_player(ctx.author.id)
            wf_name = profile.get("warframe")
            if not wf_name:
                await ctx.send(
                    "<:wf_lotus:1499651243101126816> No Warframe selected. "
                    "Use `!warframe` first, or specify an ID: `!warframe upgrades excalibur`",
                    delete_after=10,
                )
                return
            from data.warframes import WARFRAMES
            warframe_id = next(
                (k for k, v in WARFRAMES.items() if v["name"] == wf_name),
                wf_name.lower(),
            )

        warframe_id = warframe_id.lower().strip()
        wf = _get_warframe(warframe_id)
        if wf is None:
            available = ", ".join(f"`{k}`" for k in _db()["warframes"])
            await ctx.send(
                f"<:wf_lotus:1499651243101126816> Warframe `{warframe_id}` not found.\n"
                f"Available: {available}",
                delete_after=10,
            )
            return

        # Reset session when the command is explicitly invoked
        wf_data = _db()["warframes"][warframe_id]
        num_slots = len(wf_data["mod_slots"])
        _SESSIONS[ctx.author.id] = {
            "warframe_id": warframe_id,
            "equipped": [None] * num_slots,
            "selected_uuid": None,
            "page": 0,
        }

        layout = _build_layout(ctx.author.id, warframe_id)
        await ctx.send(view=layout)

    @upgrades_cmd.error
    async def upgrades_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UpgradesCog(bot))
