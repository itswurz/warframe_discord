# utils/mods_ui.py
# ─────────────────────────────────────────────────────────────────────────────
# Warframe mod configuration UI — !warframe mods <warframe_id>
#
# Design principles:
#   • ALL data comes from warframes.json + mods.json — zero hardcoded mod stats.
#   • Only WARFRAME-category mods from the player's own mod_collection may be
#     equipped in the !warframe mods panel. Weapon/stance mods are excluded.
#   • Each mod instance is INDIVIDUAL — the select menu shows every UUID
#     separately so the player picks an exact copy, not just a mod name.
#   • Equipping marks the mod UUID as consumed on that warframe instance_id.
#     The same UUID cannot be used on another Warframe until removed.
#     The same mod NAME cannot appear twice on the same Warframe.
#   • Stats are computed using each mod's ACTUAL CURRENT RANK (rank_scaling),
#     not just max stats — so a rank-3 Vitality shows the rank-3 HP bonus.
#   • Capacity uses rank-scaled drain (wiki formula: linear base→max per rank).
#   • Capacity bar turns red on over-cap.
#   • Full Components v2 layout (Containers, ActionRows, TextDisplays).
#
# UUID identity bridge with !mods:
#   Both !mods and !warframe mods read/write the SAME profile["mod_collection"].
#   Every UUID displayed here is the same UUID used in:
#     !mods view <UUID>       — inspect the mod
#     !mods upgrade <UUID>    — rank it up
#   This makes the two commands complementary views on the same data.
#
# Persistence schema written to each warframe roster entry:
#   "equipped_mods": {
#       "0": { "mod_uuid": str, "mod_name": str, "codex_uuid": str } | null,
#       "1": null,
#       ...  (key = slot index string "0".."7")
#   }
#
# A mod instance in mod_collection is marked consumed via:
#   instance["equipped_on_warframe"] = "<warframe_instance_id>"
#   instance["tradeable"]            = False
# Removing frees it:
#   instance["equipped_on_warframe"] = None
#   instance["tradeable"]            = True
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import math
import os
from typing import Optional

import discord
from data import persistence as _pers
from utils.emojis import E

# ── Data loading ───────────────────────────────────────────────────────────────

_WF_PATH   = os.path.join(os.path.dirname(__file__), "..", "data", "warframes.json")
_MODS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "mods.json")
_DB: dict | None = None


def _db() -> dict:
    global _DB
    if _DB is None:
        with open(_WF_PATH, "r", encoding="utf-8") as f:
            wf = json.load(f)
        with open(_MODS_PATH, "r", encoding="utf-8") as f:
            md = json.load(f)
        _DB = {
            "warframes":       wf.get("warframes", {}),
            "mods":            list(md.get("mods", {}).values()),
            "rarity_order":    md.get("rarity_order", ["rare", "uncommon", "common"]),
            "slot_polarities": md.get("slot_polarities", {}),
        }
    return _DB


def reload_db() -> None:
    """Force a hot-reload of warframes.json + mods.json without restarting the bot."""
    global _DB
    _DB = None
    _db()


def _get_wf_codex(warframe_key: str) -> dict | None:
    return _db()["warframes"].get(warframe_key.lower())


def _get_codex_mod_by_uuid(codex_uuid: str) -> dict | None:
    for m in _db()["mods"]:
        if m["uuid"] == codex_uuid:
            return m
    return None


def _get_codex_mod_by_name(name: str) -> dict | None:
    name_l = name.lower()
    for m in _db()["mods"]:
        if m["name"].lower() == name_l:
            return m
    return None


def _pol_info(polarity: str) -> dict:
    return _db()["slot_polarities"].get(
        polarity.lower(),
        {"emoji": E.any, "display": polarity.capitalize()}
    )


# ── Rarity ordering ────────────────────────────────────────────────────────────

_RARITY_ORDER = {r: i for i, r in enumerate(["rare", "uncommon", "common"])}
_RARITY_TAG   = {"rare": "[R]", "uncommon": "[U]", "common": "[C]"}

# ── Stat label map (for compact description strings) ──────────────────────────
_STAT_LABELS: dict[str, str] = {
    "health_percent":               "+{:.0f}% HP",
    "shields_percent":              "+{:.0f}% Shields",
    "armor_percent":                "+{:.0f}% Armor",
    "energy_percent":               "+{:.0f}% Energy",
    "ability_efficiency_percent":   "-{:.0f}% Cost",
    "ability_duration_percent":     "+{:.0f}% Duration",
    "ability_strength_percent":     "+{:.0f}% Strength",
    "ability_range_percent":        "+{:.0f}% Range",
    "puncture_resist_percent":      "+{:.0f}% Punc.Res",
    "knockdown_chance_percent":     "+{:.0f}% KD",
    "loot_bonus_percent":           "+{:.0f}% Loot",
    "electricity_store_percent":    "+{:.0f}% Arc",
    "rifle_damage_percent":         "+{:.0f}% Rifle",
    "pistol_damage_percent":        "+{:.0f}% Pistol",
    "melee_damage_percent":         "+{:.0f}% Melee",
    "crit_chance_percent":          "+{:.0f}% Crit",
    "multishot_percent":            "+{:.0f}% Multishot",
    "status_chance_percent":        "+{:.0f}% Status",
    "ammo_max_percent":             "+{:.0f}% Ammo",
    "reload_speed_percent":         "+{:.0f}% Reload",
    "cold_damage_percent":          "+{:.0f}% Cold",
    "heat_damage_percent":          "+{:.0f}% Heat",
    "toxin_damage_percent":         "+{:.0f}% Toxin",
    "impact_damage_percent":        "+{:.0f}% Impact",
    "slash_damage_percent":         "+{:.0f}% Slash",
    "puncture_damage_percent":      "+{:.0f}% Punct.",
    "electricity_damage_percent":   "+{:.0f}% Elec.",
    "slash_proc_duration_percent":  "+{:.0f}% Bleed Dur",
    "heavy_attack_efficiency_percent": "+{:.0f}% HvyAtk",
    "combo_efficiency_percent":     "+{:.0f}% Combo Eff",
    "ammo_conversion_ratio":        "Ammo ×{:.0f}",
}


# ─────────────────────────────────────────────────────────────────────────────
# Stat computation
# ─────────────────────────────────────────────────────────────────────────────

def _stat_at_rank(codex_mod: dict, rank: int) -> dict:
    """
    Compute stats at a given rank using rank_scaling.per_rank * rank.
    Rank 0 returns the rank-1 base effect (Warframe: an unranked mod still
    provides its minimum/base stat — ranking up adds incremental bonuses).
    Falls back to the mod's max 'stats' field when no rank_scaling exists.
    """
    scaling = codex_mod.get("rank_scaling", {})
    result  = {}
    effective_rank = max(1, rank)   # rank 0 → apply rank-1 base effect
    for stat_key, scale_info in scaling.items():
        per_rank = scale_info.get("per_rank", 0)
        result[stat_key] = round(per_rank * effective_rank, 2)
    if not result:
        result = dict(codex_mod.get("stats", {}))
    return result


def _apply_bonuses(base_stats: dict, bonuses: dict[str, float]) -> dict:
    """Apply accumulated bonus dict to base stats and return final stat dict."""
    final: dict = {
        "health":  int(base_stats["health"]  * (1 + bonuses.get("health_percent",  0) / 100)),
        "shields": int(base_stats["shields"] * (1 + bonuses.get("shields_percent", 0) / 100)),
        "armor":   int(base_stats["armor"]   * (1 + bonuses.get("armor_percent",   0) / 100)),
        "energy":  int(base_stats["energy"]  * (1 + bonuses.get("energy_percent",  0) / 100)),
    }
    for extra, bonus_key in (
        ("ability_efficiency_bonus", "ability_efficiency_percent"),
        ("puncture_resist_bonus",    "puncture_resist_percent"),
        ("knockdown_chance_bonus",   "knockdown_chance_percent"),
        ("loot_bonus",               "loot_bonus_percent"),
        ("electricity_store_bonus",  "electricity_store_percent"),
    ):
        if bonus_key in bonuses:
            final[extra] = int(bonuses[bonus_key])
    return final


def compute_final_stats(warframe_key: str, slot_mods: list[dict | None]) -> dict:
    """
    Apply all provided mod dicts (at their stored max stats) to base_stats.
    Used when no profile is available (e.g. quick previews).
    For accurate rank-aware display, use compute_final_stats_with_ranks().
    """
    codex = _get_wf_codex(warframe_key)
    if not codex:
        return {}
    base    = codex["base_stats"]
    bonuses: dict[str, float] = {}
    for mod in slot_mods:
        if mod is None:
            continue
        for stat_key, val in mod.get("stats", {}).items():
            if isinstance(val, (int, float)):
                bonuses[stat_key] = bonuses.get(stat_key, 0.0) + val
    return _apply_bonuses(base, bonuses)


def compute_final_stats_with_ranks(warframe_key: str, wf_instance: dict, profile: dict) -> dict:
    """
    Apply each equipped mod at its ACTUAL current rank (from mod_collection).
    Used by combat sessions and the warframe view embed for accurate values.
    """
    codex = _get_wf_codex(warframe_key)
    if not codex:
        return {}
    base    = codex["base_stats"]
    em      = wf_instance.get("equipped_mods", {})
    bonuses: dict[str, float] = {}

    for slot_def in codex["mod_slots"]:
        idx       = slot_def["index"]
        slot_data = em.get(str(idx))
        if not slot_data:
            continue
        mod_uuid  = slot_data.get("mod_uuid", "")
        codex_mod = _get_codex_mod_by_uuid(slot_data.get("codex_uuid", ""))
        if not codex_mod:
            continue
        rank = 0
        for m in profile.get("mod_collection", []):
            if m["uuid"] == mod_uuid:
                rank = m.get("rank", 0)
                break
        for stat_key, val in _stat_at_rank(codex_mod, rank).items():
            if isinstance(val, (int, float)):
                bonuses[stat_key] = bonuses.get(stat_key, 0.0) + val

    return _apply_bonuses(base, bonuses)


def compute_capacity(warframe_key: str, slot_assignments: dict[int, dict | None]) -> tuple[int, int]:
    """
    Return (used_capacity, max_capacity) using max_drain for each mod (no rank).
    Applies polarity-match halving.
    """
    codex = _get_wf_codex(warframe_key)
    if not codex:
        return 0, 30
    max_cap = codex.get("mod_capacity", 30)
    used    = 0
    for slot_def in codex["mod_slots"]:
        idx      = slot_def["index"]
        slot_pol = slot_def["polarity"]
        mod      = slot_assignments.get(idx)
        if mod is None:
            continue
        mod_pol = mod.get("polarity", "any")
        drain   = mod.get("max_drain", 10)
        if slot_pol != "any" and mod_pol != "any" and slot_pol == mod_pol:
            drain = math.ceil(drain / 2)
        used += drain
    return used, max_cap


def compute_capacity_with_ranks(
    warframe_key: str, wf_instance: dict, profile: dict
) -> tuple[int, int]:
    """
    Return (used_capacity, max_capacity) using each mod's RANK-SCALED drain.

    Wiki drain formula:
        drain_at_rank = ceil(base_drain + (max_drain - base_drain) * rank / max_rank)

    Polarity-match halving applied after rank scaling.
    This is shown in the mods panel capacity bar.
    """
    codex = _get_wf_codex(warframe_key)
    if not codex:
        return 0, 30
    max_cap = codex.get("mod_capacity", 30)
    em      = wf_instance.get("equipped_mods", {})
    used    = 0

    for slot_def in codex["mod_slots"]:
        idx       = slot_def["index"]
        slot_pol  = slot_def["polarity"]
        slot_data = em.get(str(idx))
        if not slot_data:
            continue
        mod_uuid  = slot_data.get("mod_uuid", "")
        codex_mod = _get_codex_mod_by_uuid(slot_data.get("codex_uuid", ""))
        if not codex_mod:
            continue

        rank    = 0
        max_r   = codex_mod.get("max_rank", 5)
        for m in profile.get("mod_collection", []):
            if m["uuid"] == mod_uuid:
                rank = m.get("rank", 0)
                break

        base_drain = codex_mod.get("base_drain", 2)
        max_drain  = codex_mod.get("max_drain", 10)
        if max_r > 0:
            drain = math.ceil(base_drain + (max_drain - base_drain) * rank / max_r)
        else:
            drain = base_drain

        mod_pol = codex_mod.get("polarity", "any")
        if slot_pol != "any" and mod_pol != "any" and slot_pol == mod_pol:
            drain = math.ceil(drain / 2)

        used += drain

    return used, max_cap


# ─────────────────────────────────────────────────────────────────────────────
# Profile helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_wf_instance(profile: dict, instance_id: str) -> dict | None:
    """Find a warframe roster entry by instance_id (case-insensitive)."""
    inst_upper = instance_id.upper()
    for wf in profile.get("warframe_roster", []):
        if wf.get("instance_id", "").upper() == inst_upper:
            return wf
    return None


def get_wf_equipped_mods(wf_instance: dict) -> dict[str, dict | None]:
    """Return the equipped_mods dict, creating it if absent."""
    return wf_instance.setdefault("equipped_mods", {})


def _slot_assignments_from_instance(
    wf_instance: dict, warframe_key: str
) -> dict[int, dict | None]:
    """Build {slot_index: codex_mod_dict | None} for capacity + stat helpers."""
    codex = _get_wf_codex(warframe_key)
    if not codex:
        return {}
    em  = get_wf_equipped_mods(wf_instance)
    out = {}
    for slot_def in codex["mod_slots"]:
        idx       = slot_def["index"]
        slot_data = em.get(str(idx))
        if slot_data:
            codex_mod = _get_codex_mod_by_uuid(slot_data.get("codex_uuid", ""))
            out[idx]  = codex_mod
        else:
            out[idx] = None
    return out


def _is_warframe_mod(mod_name: str) -> bool:
    """
    Return True only if this mod is present in mods.json with
    category == "warframe" (case-insensitive).

    Mods NOT in the codex are always False — they are weapon/stance/unknown
    mods that don't belong in the Warframe slot panel.
    """
    entry = _get_codex_mod_by_name(mod_name)
    if entry is None:
        return False
    return entry.get("category", "").lower() == "warframe"


def get_player_available_mods(profile: dict, wf_instance: dict) -> list[dict]:
    """
    Return all mod_collection instances the player may equip in the Warframe panel.

    Filtering (strict):
      1. Mod must be Warframe-category (verified against mods.json).
      2. mod["equipped_on_warframe"] must be None or equal this instance_id.
      3. No duplicate mod NAME on the same Warframe (only the already-equipped
         copy of a duplicate name is shown; other copies are hidden).

    Each entry is a raw mod_collection dict — the UUID field is the same UUID
    shown in !mods and used with !mods upgrade / !mods view.
    """
    instance_id = wf_instance["instance_id"]
    em          = get_wf_equipped_mods(wf_instance)

    equipped_names_other: set[str] = set()
    equipped_uuids_here:  set[str] = set()
    for slot_data in em.values():
        if slot_data:
            equipped_names_other.add(slot_data.get("mod_name", "").lower())
            equipped_uuids_here.add(slot_data.get("mod_uuid", ""))

    available: list[dict] = []
    for inst in profile.get("mod_collection", []):
        mod_uuid = inst["uuid"]
        mod_name = inst["name"]
        eq_on    = inst.get("equipped_on_warframe")

        # Rule 1 — Warframe-category only
        if not _is_warframe_mod(mod_name):
            continue

        # Rule 2 — not locked to a different warframe
        if eq_on and eq_on != instance_id:
            continue

        name_l = mod_name.lower()

        # Already equipped here (by this UUID) — always include so it's visible
        if mod_uuid in equipped_uuids_here:
            available.append(inst)
            continue

        # Rule 3 — name already taken by a different UUID on this warframe
        if name_l in equipped_names_other:
            continue

        available.append(inst)

    available.sort(key=lambda x: (
        _RARITY_ORDER.get(x.get("rarity", "common"), 99),
        x["name"],
        x["uuid"],
    ))
    return available


# ─────────────────────────────────────────────────────────────────────────────
# Equip / unequip
# ─────────────────────────────────────────────────────────────────────────────

def equip_mod_on_warframe(
    profile:     dict,
    wf_instance: dict,
    slot_idx:    int,
    mod_uuid:    str,
) -> tuple[bool, str]:
    """
    Equip one mod from the player's mod_collection into a Warframe slot.
    Returns (success, message).

    Validates slot existence, category restriction, cross-warframe lock,
    and duplicate-name constraint before writing.
    """
    instance_id  = wf_instance["instance_id"]
    warframe_key = wf_instance["warframe_key"]

    codex = _get_wf_codex(warframe_key)
    if not codex:
        return False, f"Codex entry for `{warframe_key}` not found."

    valid_indices = [s["index"] for s in codex["mod_slots"]]
    if slot_idx not in valid_indices:
        return False, f"Slot {slot_idx} does not exist on **{wf_instance['warframe_name']}**."

    mod_inst = next(
        (m for m in profile.get("mod_collection", []) if m["uuid"] == mod_uuid), None
    )
    if mod_inst is None:
        return False, f"Mod `{mod_uuid}` not found in your collection."

    mod_name = mod_inst["name"]

    if not _is_warframe_mod(mod_name):
        return False, (
            f"**{mod_name}** is not a Warframe mod.\n"
            "Only Warframe-category mods (Vitality, Redirection, etc.) "
            "can be slotted in Warframe mod slots."
        )

    eq_on = mod_inst.get("equipped_on_warframe")
    if eq_on and eq_on != instance_id:
        return False, (
            f"**{mod_name}** `[{mod_uuid}]` is locked to Warframe `{eq_on}`.\n"
            f"Use `!warframe mods {eq_on}` to remove it first."
        )

    em = get_wf_equipped_mods(wf_instance)
    for s_key, s_data in em.items():
        if s_data and int(s_key) != slot_idx:
            if s_data.get("mod_name", "").lower() == mod_name.lower():
                return False, (
                    f"**{mod_name}** is already in slot {s_key}. "
                    "The same mod name cannot be slotted twice on one Warframe."
                )

    existing = em.get(str(slot_idx))
    if existing:
        _unequip_from_slot(profile, wf_instance, slot_idx)

    codex_mod  = _get_codex_mod_by_name(mod_name)
    codex_uuid = codex_mod["uuid"] if codex_mod else ""

    em[str(slot_idx)] = {
        "mod_uuid":   mod_uuid,
        "mod_name":   mod_name,
        "codex_uuid": codex_uuid,
    }
    wf_instance["equipped_mods"] = em
    mod_inst["equipped_on_warframe"] = instance_id
    mod_inst["tradeable"]            = False

    return True, f"**{mod_name}** `[{mod_uuid}]` equipped in slot {slot_idx}."


def _unequip_from_slot(profile: dict, wf_instance: dict, slot_idx: int) -> bool:
    """Free the mod in slot_idx, returning it to tradeable in mod_collection."""
    em       = get_wf_equipped_mods(wf_instance)
    existing = em.get(str(slot_idx))
    if not existing:
        return False
    mod_uuid = existing.get("mod_uuid", "")
    for m in profile.get("mod_collection", []):
        if m["uuid"] == mod_uuid:
            m["equipped_on_warframe"] = None
            m["tradeable"]            = True
            break
    em[str(slot_idx)] = None
    wf_instance["equipped_mods"] = em
    return True


def unequip_mod_from_warframe(
    profile:     dict,
    wf_instance: dict,
    slot_idx:    int,
) -> tuple[bool, str]:
    """Remove the mod in slot_idx and return it to tradeable. Returns (success, msg)."""
    em       = get_wf_equipped_mods(wf_instance)
    existing = em.get(str(slot_idx))
    if not existing:
        return False, f"Slot {slot_idx} is already empty."
    mod_name = existing.get("mod_name", "Unknown")
    mod_uuid = existing.get("mod_uuid", "")
    _unequip_from_slot(profile, wf_instance, slot_idx)
    return True, f"**{mod_name}** `[{mod_uuid}]` removed from slot {slot_idx}."


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cap_bar(used: int, cap: int, length: int = 10) -> str:
    ratio  = min(1.0, used / max(1, cap))
    filled = round(ratio * length)
    bar    = "█" * filled + "░" * (length - filled)
    over   = "  ⚠️ **OVER CAPACITY**" if used > cap else ""
    return f"`{bar}` **{used} / {cap}**{over}"


def _delta_str(base: int, final: int) -> str:
    diff = final - base
    if diff == 0:
        return f"**{final}**"
    sign = "+" if diff > 0 else ""
    return f"**{final}** *({sign}{diff})*"


def _stats_line(base_stats: dict, final_stats: dict) -> str:
    parts = [
        f"<a:health:1499636458309423215> {_delta_str(base_stats['health'],  final_stats.get('health',  base_stats['health']))}",
        f"{E.shield} {_delta_str(base_stats['shields'], final_stats.get('shields', base_stats['shields']))}",
        f"{E.defense} {_delta_str(base_stats['armor'],  final_stats.get('armor',  base_stats['armor']))}",
        f"<a:energy_orb:1499636329842212964> {_delta_str(base_stats['energy'],  final_stats.get('energy',  base_stats['energy']))}",
    ]
    if final_stats.get("ability_efficiency_bonus"):
        parts.append(f"{E.mod('Streamline')} **-{final_stats['ability_efficiency_bonus']}%** cost")
    if final_stats.get("puncture_resist_bonus"):
        parts.append(f"{E.puncture} **+{final_stats['puncture_resist_bonus']}%** Punc.Res")
    if final_stats.get("knockdown_chance_bonus"):
        parts.append(f"{E.stunned} **+{final_stats['knockdown_chance_bonus']}%** KD")
    if final_stats.get("loot_bonus"):
        parts.append(f"🔓 **+{final_stats['loot_bonus']}%** Loot")
    if final_stats.get("electricity_store_bonus"):
        parts.append(f"{E.electricity} **+{final_stats['electricity_store_bonus']}%** Arc")
    return "  ".join(parts)


def _polarity_match_tag(slot_pol: str, mod_pol: str) -> str:
    if slot_pol == "any" or mod_pol == "any":
        return "⚪"
    return "✅" if slot_pol == mod_pol else "❌"


def _rank_drain(codex_mod: dict, rank: int) -> int:
    """
    Drain at a given rank.
    Wiki: linear interpolation — base_drain at rank 0, max_drain at max_rank.
    """
    base_drain = codex_mod.get("base_drain", 2)
    max_drain  = codex_mod.get("max_drain", 10)
    max_r      = codex_mod.get("max_rank", 5)
    if max_r <= 0:
        return base_drain
    return math.ceil(base_drain + (max_drain - base_drain) * rank / max_r)


def _stat_desc_at_rank(codex_mod: dict, rank: int) -> str:
    """
    Short human-readable stat string for a mod at its current rank.
    Used in select menu descriptions and hint blocks.
    e.g. "+20% HP, +20% Shields"
    Rank 0 shows the base (rank-1) effect with a note.
    """
    ranked = _stat_at_rank(codex_mod, rank)
    if not ranked:
        desc = codex_mod.get("description", "")
        return (desc[:80] + "…") if len(desc) > 80 else desc
    parts = []
    for sk, val in ranked.items():
        tmpl = _STAT_LABELS.get(sk, "+{:.0f}% " + sk)
        parts.append(tmpl.format(val))
    base_str = ", ".join(parts[:3])
    if rank == 0:
        return f"{base_str} (base — upgrade to increase)"
    return base_str


# ─────────────────────────────────────────────────────────────────────────────
# In-memory page / selection state
# ─────────────────────────────────────────────────────────────────────────────

_PAGE_STATE: dict[int, dict] = {}
_PAGE_SIZE  = 25


def _get_state(user_id: int, instance_id: str) -> dict:
    if (
        user_id not in _PAGE_STATE
        or _PAGE_STATE[user_id].get("instance_id") != instance_id
    ):
        _PAGE_STATE[user_id] = {
            "instance_id":   instance_id,
            "selected_uuid": None,
            "page":          0,
        }
    return _PAGE_STATE[user_id]


def _set_selected(user_id: int, instance_id: str, uuid: str | None) -> None:
    _get_state(user_id, instance_id)["selected_uuid"] = uuid


def _set_page(user_id: int, instance_id: str, page: int) -> None:
    _get_state(user_id, instance_id)["page"] = page


# ─────────────────────────────────────────────────────────────────────────────
# ContainerBuilder (Components v2)
# ─────────────────────────────────────────────────────────────────────────────

class _CB:
    """Minimal Components v2 container builder — matches comptest.py pattern."""

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


# ─────────────────────────────────────────────────────────────────────────────
# Main layout builder
# ─────────────────────────────────────────────────────────────────────────────

def build_mods_layout(
    user_id:     int,
    profile:     dict,
    wf_instance: dict,
) -> discord.ui.LayoutView:
    """
    Build and return the full LayoutView for !warframe mods <id>.

    Container 1 — Header:
      • Warframe name · instance ID · level · active flag
      • Live stats: base → final with (+delta) for equipped mods at actual rank
      • Capacity bar: rank-scaled drain with polarity-match halving
      • Slot overview: polarity emoji + match tag per slot
      • Up to 8 slot buttons (rows of 4): click to equip selected / unequip

    Container 2 — Mod Selection:
      • Mod count summary
      • Hint block: shows full UUID + drain + stat desc when a mod is selected
      • Select menu: label = "Name [R] RX/Y ★ | UUID", desc = stats + drain
      • Pagination row + Clear button

    Only WARFRAME-category mods are shown. The UUID in every entry is the
    same UUID used by !mods view and !mods upgrade.
    """
    instance_id  = wf_instance["instance_id"]
    warframe_key = wf_instance["warframe_key"]
    wf_name      = wf_instance["warframe_name"]
    level        = wf_instance.get("level", 0)
    is_active    = wf_instance.get("is_active", False)
    state        = _get_state(user_id, instance_id)
    sel_uuid     = state["selected_uuid"]
    page         = state["page"]

    codex = _get_wf_codex(warframe_key)
    if codex is None:
        layout = discord.ui.LayoutView()
        layout.add_item(
            _CB(accent_colour=0x7B1515)
            .text(
                f"❌ Codex entry for `{warframe_key}` not found in `warframes.json`.\n"
                "The Warframe is in your roster but has no mod data. "
                "An admin may need to update the codex JSON."
            )
            .build()
        )
        return layout

    base_stats   = codex["base_stats"]
    em           = get_wf_equipped_mods(wf_instance)

    # Rank-aware stats and capacity for live display
    final_stats  = compute_final_stats_with_ranks(warframe_key, wf_instance, profile)
    used, cap    = compute_capacity_with_ranks(warframe_key, wf_instance, profile)
    accent       = 0x1A7A3C if used <= cap else 0x7B1515

    # ─────────────────────────────────────────────────────────────────────────
    # Slot buttons
    # ─────────────────────────────────────────────────────────────────────────

    def _make_slot_cb(captured_idx: int, captured_uid: int, captured_iid: str):
        async def _cb(interaction: discord.Interaction) -> None:
            if interaction.user.id != captured_uid:
                await interaction.response.send_message("Not your panel.", ephemeral=True)
                return

            _profile = await _pers.load_player(captured_uid)
            _wf_inst = get_wf_instance(_profile, captured_iid)
            if _wf_inst is None:
                await interaction.response.send_message(
                    "❌ Warframe instance not found in your roster.", ephemeral=True
                )
                return

            _state = _get_state(captured_uid, captured_iid)
            _sel   = _state["selected_uuid"]

            if _sel is None:
                # No selection → remove mod from this slot
                ok, msg = unequip_mod_from_warframe(_profile, _wf_inst, captured_idx)
                if not ok:
                    # Already empty — just redraw
                    await interaction.response.edit_message(
                        view=build_mods_layout(captured_uid, _profile, _wf_inst)
                    )
                    return
                await _pers.save_player(_profile)
            else:
                # Mod selected → equip into this slot
                ok, msg = equip_mod_on_warframe(_profile, _wf_inst, captured_idx, _sel)
                if not ok:
                    _set_selected(captured_uid, captured_iid, None)
                    await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
                    return
                await _pers.save_player(_profile)
                _set_selected(captured_uid, captured_iid, None)

            # Reload from disk so the display reflects the actual saved state
            _profile2 = await _pers.load_player(captured_uid)
            _wf_inst2 = get_wf_instance(_profile2, captured_iid)
            await interaction.response.edit_message(
                view=build_mods_layout(captured_uid, _profile2, _wf_inst2)
            )
        return _cb

    slot_btns: list[discord.ui.Button] = []
    for slot_def in codex["mod_slots"]:
        idx       = slot_def["index"]
        slot_pol  = slot_def["polarity"]
        pi        = _pol_info(slot_pol)
        slot_data = em.get(str(idx))

        if slot_data:
            mod_name  = slot_data["mod_name"]
            mod_uuid  = slot_data.get("mod_uuid", "")
            # UUID lookup first; if UUID is stale/empty fall back to name lookup
            codex_mod = (
                _get_codex_mod_by_uuid(slot_data.get("codex_uuid", ""))
                or _get_codex_mod_by_name(mod_name)
            )
            mod_pol   = codex_mod["polarity"] if codex_mod else "any"
            match_tag = _polarity_match_tag(slot_pol, mod_pol)
            short_uuid = mod_uuid[-4:] if len(mod_uuid) >= 4 else mod_uuid
            label      = f"{match_tag} {mod_name[:14]}·{short_uuid}"
            # Use mod icon if available; never fall back to polarity emoji for
            # an occupied slot — use a neutral placeholder instead
            _mod_rarity = next(
                (m.get("rarity", "common") for m in profile.get("mod_collection", [])
                 if m.get("uuid") == mod_uuid),
                "common"
            )
            emoji = E.mod(mod_name, _mod_rarity)
            style      = (
                discord.ButtonStyle.success if match_tag == "✅"
                else discord.ButtonStyle.primary
            )
        else:
            label = pi["display"]
            emoji = pi["emoji"]
            style = discord.ButtonStyle.secondary

        btn = discord.ui.Button(
            style     = style,
            label     = label,
            emoji     = emoji,
            custom_id = f"mods_slot_{idx}_{user_id}_{instance_id}",
        )
        btn.callback = _make_slot_cb(idx, user_id, instance_id)
        slot_btns.append(btn)

    # ─────────────────────────────────────────────────────────────────────────
    # Available mods — Warframe-category only, individual UUID instances
    # ─────────────────────────────────────────────────────────────────────────
    available   = get_player_available_mods(profile, wf_instance)
    total_pages = max(1, math.ceil(len(available) / _PAGE_SIZE))
    page        = min(page, total_pages - 1)
    page_mods   = available[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    # ─────────────────────────────────────────────────────────────────────────
    # Select menu — UUID is the primary identifier, matching !mods system
    # ─────────────────────────────────────────────────────────────────────────
    sel_menu: discord.ui.Select | None = None
    if page_mods:
        options = []
        for inst in page_mods:
            cm      = _get_codex_mod_by_name(inst["name"])
            rarity  = inst.get("rarity", "common")
            rtag    = _RARITY_TAG.get(rarity, "")
            rank    = inst.get("rank", 0)
            max_r   = inst.get("max_rank", cm.get("max_rank", 5) if cm else 5)
            eq_here = inst.get("equipped_on_warframe") == instance_id
            eq_tag  = " ★" if eq_here else ""
            icon    = E.mod(inst["name"], rarity)

            # Label: "Vitality [R] R5/10 ★ | A9X4M2Q"
            # UUID after the pipe is the shared identity with !mods
            label_str = f"{inst['name']} {rtag} R{rank}/{max_r}{eq_tag} | {inst['uuid']}"

            # Description: stats at current rank + polarity + drain at this rank
            desc_parts: list[str] = []
            if cm:
                stat_str = _stat_desc_at_rank(cm, rank)
                if stat_str:
                    desc_parts.append(stat_str)
                pol_name  = cm.get("polarity", "any").capitalize()
                cur_drain = _rank_drain(cm, rank)
                desc_parts.append(f"{pol_name} · {cur_drain}dr")
            desc = "  ·  ".join(desc_parts) if desc_parts else "No codex data"

            options.append(discord.SelectOption(
                label       = label_str[:100],
                value       = inst["uuid"],
                description = desc[:100],
                emoji       = icon,
                default     = (sel_uuid == inst["uuid"]),
            ))

        sel_menu = discord.ui.Select(
            custom_id   = f"mods_select_{user_id}_{instance_id}",
            placeholder = "Pick a Warframe mod — UUID after | links to !mods…",
            min_values  = 1,
            max_values  = 1,
            options     = options,
        )

        def _make_sel_cb(captured_uid=user_id, captured_iid=instance_id):
            async def _sel_cb(interaction: discord.Interaction) -> None:
                if interaction.user.id != captured_uid:
                    await interaction.response.send_message("Not your panel.", ephemeral=True)
                    return
                chosen = interaction.data["values"][0]
                _set_selected(captured_uid, captured_iid, chosen)
                _profile = await _pers.load_player(captured_uid)
                _wf_inst = get_wf_instance(_profile, captured_iid)
                await interaction.response.edit_message(
                    view=build_mods_layout(captured_uid, _profile, _wf_inst)
                )
            return _sel_cb

        sel_menu.callback = _make_sel_cb()

    # ─────────────────────────────────────────────────────────────────────────
    # Pagination + control buttons
    # ─────────────────────────────────────────────────────────────────────────
    prev_btn = discord.ui.Button(
        style     = discord.ButtonStyle.secondary,
        label     = "◀ Prev",
        custom_id = f"mods_prev_{user_id}_{instance_id}",
        disabled  = (page <= 0),
    )
    next_btn = discord.ui.Button(
        style     = discord.ButtonStyle.secondary,
        label     = "Next ▶",
        custom_id = f"mods_next_{user_id}_{instance_id}",
        disabled  = (page >= total_pages - 1),
    )
    clear_btn = discord.ui.Button(
        style     = discord.ButtonStyle.danger,
        label     = "Clear",
        emoji     = "✖️",
        custom_id = f"mods_clear_{user_id}_{instance_id}",
        disabled  = (sel_uuid is None),
    )

    # Indicator button: shows selected mod + UUID or page counter
    if sel_uuid:
        sel_inst = next(
            (m for m in profile.get("mod_collection", []) if m["uuid"] == sel_uuid), None
        )
        sel_name  = sel_inst["name"] if sel_inst else "Selected"
        sel_rank  = sel_inst.get("rank", 0) if sel_inst else 0
        sel_cm    = _get_codex_mod_by_name(sel_name) if sel_inst else None
        ind_label = f"✅ {sel_name} R{sel_rank} · {sel_uuid}"[:80]
        ind_emoji = E.mod(sel_name, sel_inst.get("rarity", "common") if sel_inst else "common")
    else:
        ind_label = f"Pg {page + 1}/{total_pages}  ·  {len(available)} Warframe mod(s)"
        ind_emoji = None

    ind_btn = discord.ui.Button(
        style     = discord.ButtonStyle.secondary,
        label     = ind_label,
        custom_id = f"mods_ind_{user_id}_{instance_id}",
        disabled  = True,
    )
    if ind_emoji:
        ind_btn.emoji = ind_emoji

    def _make_page_cb(
        delta: int,
        captured_uid   = user_id,
        captured_iid   = instance_id,
        captured_total = total_pages,
        captured_page  = page,
    ):
        async def _cb(interaction: discord.Interaction) -> None:
            if interaction.user.id != captured_uid:
                await interaction.response.send_message("Not your panel.", ephemeral=True)
                return
            new_page = max(0, min(captured_total - 1, captured_page + delta))
            _set_page(captured_uid, captured_iid, new_page)
            _profile = await _pers.load_player(captured_uid)
            _wf_inst = get_wf_instance(_profile, captured_iid)
            await interaction.response.edit_message(
                view=build_mods_layout(captured_uid, _profile, _wf_inst)
            )
        return _cb

    def _make_clear_cb(captured_uid=user_id, captured_iid=instance_id):
        async def _cb(interaction: discord.Interaction) -> None:
            if interaction.user.id != captured_uid:
                await interaction.response.send_message("Not your panel.", ephemeral=True)
                return
            _set_selected(captured_uid, captured_iid, None)
            _profile = await _pers.load_player(captured_uid)
            _wf_inst = get_wf_instance(_profile, captured_iid)
            await interaction.response.edit_message(
                view=build_mods_layout(captured_uid, _profile, _wf_inst)
            )
        return _cb

    prev_btn.callback  = _make_page_cb(-1)
    next_btn.callback  = _make_page_cb(+1)
    clear_btn.callback = _make_clear_cb()

    # ─────────────────────────────────────────────────────────────────────────
    # Header container
    # ─────────────────────────────────────────────────────────────────────────
    active_tag     = "  🟢 **ACTIVE**" if is_active else ""
    equipped_count = sum(1 for v in em.values() if v)

    # Slot overview: polarity emoji + match indicator per slot
    slot_summary_parts = []
    for slot_def in codex["mod_slots"]:
        idx = slot_def["index"]
        sp  = slot_def["polarity"]
        pi  = _pol_info(sp)
        sd  = em.get(str(idx))
        if sd:
            # UUID first; fall back to name so stale codex_uuids still resolve
            cm  = (
                _get_codex_mod_by_uuid(sd.get("codex_uuid", ""))
                or _get_codex_mod_by_name(sd.get("mod_name", ""))
            )
            mp  = cm["polarity"] if cm else "any"
            tag = _polarity_match_tag(sp, mp)
            slot_summary_parts.append(f"{pi['emoji']}{tag}")
        else:
            slot_summary_parts.append(f"{pi['emoji']}·")
    slot_row_str = "  ".join(slot_summary_parts)

    hdr = (
        _CB(accent_colour=accent)
        .text(
            f"{E.lotus}  **{wf_name}**{active_tag}  ·  "
            f"`{instance_id}`  ·  Level **{level}**\n"
            f"{_stats_line(base_stats, final_stats)}\n"
            f"**Slots:** {slot_row_str}"
        )
        .sep(visible=False)
        .text(f"**Capacity:** {_cap_bar(used, cap)}")
        .sep()
    )
    for i in range(0, len(slot_btns), 4):
        hdr.row(*slot_btns[i:i + 4])

    # ─────────────────────────────────────────────────────────────────────────
    # Mod panel container
    # ─────────────────────────────────────────────────────────────────────────
    if sel_uuid:
        sel_inst = next(
            (m for m in profile.get("mod_collection", []) if m["uuid"] == sel_uuid), None
        )
        if sel_inst:
            cm     = _get_codex_mod_by_name(sel_inst["name"])
            rarity = sel_inst.get("rarity", "common")
            rank   = sel_inst.get("rank", 0)
            max_r  = sel_inst.get("max_rank", cm.get("max_rank", 5) if cm else 5)
            # Build hint lines — UUID is shown prominently as the identity bridge
            hint_lines = [
                f"{E.mod(sel_inst['name'], rarity)} **{sel_inst['name']}** "
                f"{_RARITY_TAG.get(rarity, '')}  ·  Rank **{rank} / {max_r}**",
                f"{E.combo} **UUID:** `{sel_uuid}`",
            ]
            if cm:
                pi_       = _pol_info(cm["polarity"])
                cur_drain = _rank_drain(cm, rank)
                stat_str  = _stat_desc_at_rank(cm, rank)
                hint_lines.append(
                    f"{pi_['emoji']} **{pi_['display']}**  ·  "
                    f"Drain at R{rank}: **{cur_drain}**"
                    + (f"  ·  {stat_str}" if stat_str else "")
                )
                if cm.get("description"):
                    hint_lines.append(f"*{cm['description'][:130]}*")
            hint_lines += [
                "",
                "**Click a slot button above** to equip this copy, or pick a different mod.",
                f"Use `!mods upgrade {sel_uuid}` to rank up before equipping.",
            ]
            hint = "\n".join(hint_lines)
        else:
            # UUID no longer exists — stale state
            _set_selected(user_id, instance_id, None)
            hint = (
                f"Mod `{sel_uuid}` is no longer in your collection (selection cleared).\n"
                "Please pick a different mod from the list below."
            )
    else:
        owned_count = len(available)
        if not available:
            hint = (
                "**No Warframe mods in your collection yet.**\n"
                "Earn mods from enemy drops — **Vitality**, **Redirection**, "
                "**Steel Fiber**, **Flow**, **Streamline**, **Diamond Skin**, "
                "and more drop from Grineer enemies.\n\n"
                "Use `!mods` to browse your full collection and see all UUIDs."
            )
        else:
            hint = (
                f"**{owned_count} Warframe mod instance(s) available.**\n"
                "Select a mod from the dropdown — the UUID after **|** is the same UUID "
                "used with `!mods view <UUID>` and `!mods upgrade <UUID>`.\n"
                "Then **click a slot button above** to equip that specific copy.\n"
                "Clicking an **occupied slot with nothing selected** removes that mod."
            )

    mod_count_str = (
        f"**{equipped_count} / {len(codex['mod_slots'])}** slots filled  ·  "
        f"**{len(available)}** Warframe mod(s) available"
    )

    mod_panel = _CB(accent_colour=0x2B4A6B)
    mod_panel.text(f"**Mod Configuration**  ·  {mod_count_str}")
    mod_panel.text(hint)
    mod_panel.sep(visible=False)
    if sel_menu is not None:
        mod_panel.row(sel_menu)
    mod_panel.row(prev_btn, ind_btn, next_btn, clear_btn)

    layout = discord.ui.LayoutView()
    layout.add_item(hdr.build())
    layout.add_item(mod_panel.build())
    return layout


# ─────────────────────────────────────────────────────────────────────────────
# Public API used externally
# ─────────────────────────────────────────────────────────────────────────────

def get_active_stat_bonuses(profile: dict, wf_instance: dict) -> dict:
    """
    Return the final computed stats for a warframe instance using each mod's
    actual current rank. Called by the combat session and warframe view embed.
    """
    warframe_key = wf_instance["warframe_key"]
    return compute_final_stats_with_ranks(warframe_key, wf_instance, profile)
