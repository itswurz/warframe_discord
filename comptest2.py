# comptest.py
# ─────────────────────────────────────────────────────────────────────────────
# This was a working Components v2 UI. Learn from it to avoid making mistakes.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import math
import os

import discord

# ── Data loading ──────────────────────────────────────────────────────────────

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "warframes_mods.json")
_DB: dict | None = None


def _db() -> dict:
    global _DB
    if _DB is None:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            _DB = json.load(f)
    return _DB


def _get_warframe(warframe_id: str) -> dict | None:
    return _db()["warframes"].get(warframe_id.lower())


def _get_mods_sorted() -> list[dict]:
    order = {r: i for i, r in enumerate(_db().get("rarity_order", ["rare", "uncommon", "common"]))}
    return sorted(_db()["mods"], key=lambda m: order.get(m["rarity"], 99))


def _get_mod(uuid: str) -> dict | None:
    for m in _db()["mods"]:
        if m["uuid"] == uuid:
            return m
    return None


def _pol(polarity: str) -> dict:
    return _db()["slot_polarities"].get(polarity, {"emoji": "◻", "display": polarity.capitalize()})


# ── Session state ─────────────────────────────────────────────────────────────

# {user_id: {warframe_id, equipped: [uuid|None, ...], selected_uuid, page}}
_SESSIONS: dict[int, dict] = {}


def reset_session(user_id: int, warframe_id: str) -> None:
    wf = _get_warframe(warframe_id)
    num_slots = len(wf["mod_slots"]) if wf else 8
    _SESSIONS[user_id] = {
        "warframe_id":    warframe_id,
        "equipped":       [None] * num_slots,
        "selected_uuid":  None,
        "page":           0,
    }


def _sess(user_id: int, warframe_id: str) -> dict:
    if user_id not in _SESSIONS or _SESSIONS[user_id]["warframe_id"] != warframe_id:
        reset_session(user_id, warframe_id)
    return _SESSIONS[user_id]


# ── Stat & capacity calculation ───────────────────────────────────────────────

def _calc_stats(warframe_id: str, equipped: list[str | None]) -> dict:
    wf = _get_warframe(warframe_id)
    if not wf:
        return {}
    base  = dict(wf["base_stats"])
    final = dict(base)
    bonus: dict[str, float] = {}

    for uuid in equipped:
        if uuid is None:
            continue
        mod = _get_mod(uuid)
        if not mod:
            continue
        for k, v in mod.get("stats", {}).items():
            bonus[k] = bonus.get(k, 0) + v

    if "health_percent"           in bonus:
        final["health"]  = int(base["health"]  * (1 + bonus["health_percent"]  / 100))
    if "shields_percent"          in bonus:
        final["shields"] = int(base["shields"] * (1 + bonus["shields_percent"] / 100))
    if "armor_percent"            in bonus:
        final["armor"]   = int(base["armor"]   * (1 + bonus["armor_percent"]   / 100))
    if "energy_percent"           in bonus:
        final["energy"]  = int(base["energy"]  * (1 + bonus["energy_percent"]  / 100))
    if "ability_efficiency_percent" in bonus:
        final["ability_efficiency_bonus"] = int(bonus["ability_efficiency_percent"])
    if "puncture_resist_percent"  in bonus:
        final["puncture_resist_bonus"]    = int(bonus["puncture_resist_percent"])

    return final


def _calc_capacity(warframe_id: str, equipped: list[str | None]) -> tuple[int, int]:
    wf = _get_warframe(warframe_id)
    if not wf:
        return 0, 30
    max_cap = wf.get("mod_capacity", 30)
    used    = 0
    for slot_def in wf["mod_slots"]:
        idx  = slot_def["index"]
        uuid = equipped[idx] if idx < len(equipped) else None
        if uuid is None:
            continue
        mod = _get_mod(uuid)
        if not mod:
            continue
        drain    = mod.get("max_drain", 10)
        slot_pol = slot_def["polarity"]
        mod_pol  = mod.get("polarity", "any")
        if slot_pol != "any" and mod_pol != "any" and slot_pol == mod_pol:
            drain = math.ceil(drain / 2)
        used += drain
    return used, max_cap


# ── ContainerBuilder (matches comptest.py pattern) ────────────────────────────

class _CB:
    def __init__(self, **kw):
        self.items = []
        self.kw    = kw

    def text(self, content: str):
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


# ── Display helpers ───────────────────────────────────────────────────────────

def _cap_bar(used: int, cap: int, length: int = 10) -> str:
    ratio  = min(1.0, used / max(1, cap))
    filled = round(ratio * length)
    bar    = "█" * filled + "░" * (length - filled)
    over   = "  ⚠️ **OVER CAPACITY!**" if used > cap else ""
    return f"`{bar}` **{used}/{cap}**{over}"


def _stats_line(warframe_id: str, equipped: list[str | None]) -> str:
    s = _calc_stats(warframe_id, equipped)
    if not s:
        return "*No stats.*"
    parts = [
        f"<a:health:1499636458309423215> **{s['health']}**",
        f"<:wf_shield:1499636531755745280> **{s['shields']}**",
        f"<:damage_reduction:1499651603945226260> **{s['armor']}**",
        f"<a:energy_orb:1499636329842212964> **{s['energy']}**",
    ]
    if s.get("ability_efficiency_bonus"):
        parts.append(f"<:streamlinemod:1499760906576461825> **-{s['ability_efficiency_bonus']}% cost**")
    if s.get("puncture_resist_bonus"):
        parts.append(f"<:puncture:1499594734421803060> **+{s['puncture_resist_bonus']}% resist**")
    return "  ".join(parts)


# ── Slot buttons ──────────────────────────────────────────────────────────────

def _slot_button(slot_def: dict, uuid: str | None, selected_uuid: str | None,
                 user_id: int, warframe_id: str) -> discord.ui.Button:
    slot_idx = slot_def["index"]
    slot_pol = slot_def["polarity"]
    mod      = _get_mod(uuid) if uuid else None

    if mod:
        mod_pol = mod.get("polarity", "any")
        match   = slot_pol != "any" and mod_pol != "any" and slot_pol == mod_pol
        label   = f"{mod['name'][:18]}{' ✓' if match else ''}"
        emoji   = mod["icon"]
        style   = discord.ButtonStyle.success if match else discord.ButtonStyle.primary
    elif slot_pol == "any":
        label = "Empty Slot"
        emoji = "<:any:1499939092811743242>"
        style = discord.ButtonStyle.secondary
    else:
        pi    = _pol(slot_pol)
        label = pi["display"]
        emoji = pi["emoji"]
        style = discord.ButtonStyle.secondary

    btn = discord.ui.Button(
        style     = style,
        label     = label,
        emoji     = emoji,
        custom_id = f"upgrades_slot_{slot_idx}_{user_id}",
    )

    async def _cb(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        s  = _sess(user_id, warframe_id)
        sel = s["selected_uuid"]
        if sel is None:
            # No mod selected → remove equipped mod (if any)
            s["equipped"][slot_idx] = None
        else:
            # Equip selected mod into this slot
            s["equipped"][slot_idx] = sel
            s["selected_uuid"] = None
        await interaction.response.edit_message(view=build_upgrades_layout(user_id, warframe_id))

    btn.callback = _cb
    return btn


# ── Mod select menu ───────────────────────────────────────────────────────────

_PAGE_SIZE = 25


def _mod_select(page: int, selected_uuid: str | None,
                user_id: int, warframe_id: str) -> discord.ui.Select:
    all_mods  = _get_mods_sorted()
    start     = page * _PAGE_SIZE
    page_mods = all_mods[start: start + _PAGE_SIZE]

    options = []
    for m in page_mods:
        rtag = {"rare": "[R]", "uncommon": "[U]", "common": "[C]"}.get(m["rarity"], "")
        options.append(discord.SelectOption(
            label       = f"{m['name']} {rtag}",
            value       = m["uuid"],
            description = m.get("description", "")[:100],
            emoji       = m["icon"],
            default     = (selected_uuid == m["uuid"]),
        ))

    sel = discord.ui.Select(
        custom_id   = f"upgrades_modselect_{user_id}",
        placeholder = "Choose a mod to equip…",
        min_values  = 1,
        max_values  = 1,
        options     = options,
    )

    async def _cb(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        s = _sess(user_id, warframe_id)
        s["selected_uuid"] = sel.values[0]
        await interaction.response.edit_message(view=build_upgrades_layout(user_id, warframe_id))

    sel.callback = _cb
    return sel


def _pagination_buttons(page: int, total_pages: int, selected_uuid: str | None,
                        user_id: int, warframe_id: str) -> list[discord.ui.Button]:
    # Prev
    prev = discord.ui.Button(
        style=discord.ButtonStyle.secondary, label="◀ Prev",
        custom_id=f"upgrades_prev_{user_id}", disabled=(page <= 0),
    )
    async def _prev(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True); return
        _sess(user_id, warframe_id)["page"] = max(0, page - 1)
        await interaction.response.edit_message(view=build_upgrades_layout(user_id, warframe_id))
    prev.callback = _prev

    # Selected indicator (disabled display)
    if selected_uuid:
        mod       = _get_mod(selected_uuid)
        ind_label = f"✅ {mod['name']}" if mod else "✅ Selected"
        ind_emoji = mod["icon"] if mod else None
    else:
        ind_label = "None Selected"
        ind_emoji = None
    ind = discord.ui.Button(
        style=discord.ButtonStyle.secondary, label=ind_label[:80],
        custom_id=f"upgrades_ind_{user_id}", disabled=True,
    )
    if ind_emoji:
        ind.emoji = ind_emoji

    # Next
    nxt = discord.ui.Button(
        style=discord.ButtonStyle.secondary, label="Next ▶",
        custom_id=f"upgrades_next_{user_id}", disabled=(page >= total_pages - 1),
    )
    async def _nxt(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True); return
        _sess(user_id, warframe_id)["page"] = min(total_pages - 1, page + 1)
        await interaction.response.edit_message(view=build_upgrades_layout(user_id, warframe_id))
    nxt.callback = _nxt

    # Clear
    clr = discord.ui.Button(
        style=discord.ButtonStyle.danger, label="Clear", emoji="✖️",
        custom_id=f"upgrades_clr_{user_id}", disabled=(selected_uuid is None),
    )
    async def _clr(interaction: discord.Interaction) -> None:
        if interaction.user.id != user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True); return
        _sess(user_id, warframe_id)["selected_uuid"] = None
        await interaction.response.edit_message(view=build_upgrades_layout(user_id, warframe_id))
    clr.callback = _clr

    return [prev, ind, nxt, clr]


# ── Public: build the full LayoutView ────────────────────────────────────────

def build_upgrades_layout(user_id: int, warframe_id: str) -> discord.ui.LayoutView:
    s   = _sess(user_id, warframe_id)
    wf  = _get_warframe(warframe_id)

    if wf is None:
        layout = discord.ui.LayoutView()
        layout.add_item(
            _CB(accent_colour=0x7B1515)
            .text(f"❌ Warframe `{warframe_id}` not found in `warframes_mods.json`.")
            .build()
        )
        return layout

    equipped = s["equipped"]
    sel_uuid = s["selected_uuid"]
    page     = s["page"]
    used, cap = _calc_capacity(warframe_id, equipped)
    accent   = 0x1A7A3C if used <= cap else 0x7B1515

    # ── Slot buttons (max 4 per ActionRow) ───────────────────────────────────
    slot_btns = [
        _slot_button(sd, equipped[sd["index"]], sel_uuid, user_id, warframe_id)
        for sd in wf["mod_slots"]
    ]
    rows = [slot_btns[i:i+4] for i in range(0, len(slot_btns), 4)]

    header_builder = (
        _CB(accent_colour=accent)
        .text(f"<:wf_lotus:1499651243101126816>  **{wf['name']}** — Mod Configuration")
        .text(_stats_line(warframe_id, equipped))
        .sep(visible=False)
        .text(f"**Mod Capacity:** {_cap_bar(used, cap)}")
        .sep()
    )
    for row in rows:
        header_builder.row(*row)
    header = header_builder.build()

    # ── Mod selection hint ───────────────────────────────────────────────────
    if sel_uuid:
        mod      = _get_mod(sel_uuid)
        pi       = _pol(mod.get("polarity", "any")) if mod else {"emoji": "", "display": ""}
        hint     = (
            f"{mod['icon']} **{mod['name']}** selected  ·  "
            f"{pi['emoji']} {pi['display']}  ·  Drain: **{mod.get('max_drain','?')}**\n"
            f"*{mod.get('description','')}*\n\n"
            "*Click a slot to equip, or another to replace.*"
        ) if mod else "*Mod selected. Click a slot.*"
    else:
        hint = "*Select a mod below, then click a slot to equip it.\nClick an occupied slot with nothing selected to remove its mod.*"

    all_mods    = _get_mods_sorted()
    total_pages = max(1, math.ceil(len(all_mods) / _PAGE_SIZE))

    mod_panel = (
        _CB(accent_colour=0x2B4A6B)
        .text(f"**Mod Selection**  ·  Page {page + 1}/{total_pages}")
        .text(hint)
        .sep(visible=False)
        .row(_mod_select(page, sel_uuid, user_id, warframe_id))
        .row(*_pagination_buttons(page, total_pages, sel_uuid, user_id, warframe_id))
        .build()
    )

    layout = discord.ui.LayoutView()
    layout.add_item(header)
    layout.add_item(mod_panel)
    return layout
