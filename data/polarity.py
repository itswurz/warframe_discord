# data/polarity.py
# ─────────────────────────────────────────────────────────────────────────────
# Warframe Polarity System
# ─────────────────────────────────────────────────────────────────────────────
#
# Warframe wiki reference:
#   https://wiki.warframe.com/w/Polarity
#
# Rules (official):
#   • Matching polarity  → mod drain cost ÷ 2  (rounded UP to nearest int)
#   • No-match polarity  → mod drain cost × 2  (no cap in base game; TB caps at ×2)
#   • "Any" slot (Umbra  / blank in codex) → no change — treat as neutral
#   • "Any" polarity mod → no change — the mod itself is neutral
#
# Polarity identifiers used throughout this codebase:
#   "madurai"  "naramon"  "vazarin"  "zenurik"  "unairu"
#   "penjaga"  "koneksi"  "umbra"    "any"
#
# "any" is both a valid slot polarity AND a valid mod polarity.
# A slot with "any" polarity always yields NEUTRAL cost (no bonus, no penalty).
# A mod with "any" polarity always yields NEUTRAL cost regardless of slot.
#
# ─────────────────────────────────────────────────────────────────────────────
# Storage schema
# ─────────────────────────────────────────────────────────────────────────────
#
# polarities.json  ← authoritative source; never hardcode strings elsewhere
# {
#   "emojis": {
#     "madurai": "<:madurai:…>",
#     …
#   },
#   "warframes": {
#     "excalibur": {
#       "warframe_slots": ["madurai", "naramon", "any", "any"],
#       "primary_slots":  ["madurai", "naramon", "any", "any", "any", "any", "any", "any"],
#       "secondary_slots":["any", "any", "any", "any", "any", "any"],
#       "melee_slots":    ["naramon", "any", "any", "any", "any", "any", "any", "any"]
#     },
#     …
#   },
#   "weapons": {
#     "MK1-Braton": { "slots": ["madurai", "naramon", "any", …] },
#     …
#   },
#   "mods": {
#     "Serration": "madurai",
#     "Vitality":  "madurai",
#     …
#   }
# }
#
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import math
import os
from typing import Optional

_DB_PATH = os.path.join(os.path.dirname(__file__), "polarities.json")

# Module-level cache
_CACHE: dict | None = None

# ── "Any" sentinel — a slot or mod polarity that never changes cost ───────────
ANY = "any"


def _data() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            with open(_DB_PATH, "r", encoding="utf-8") as f:
                _CACHE = json.load(f)
        except FileNotFoundError:
            _CACHE = {"emojis": {}, "warframes": {}, "weapons": {}, "mods": {}}
    return _CACHE


def reload() -> None:
    """Force a reload of polarities.json (e.g. after live edits)."""
    global _CACHE
    _CACHE = None
    _data()


# ─────────────────────────────────────────────────────────────────────────────
# Emoji helpers
# ─────────────────────────────────────────────────────────────────────────────

def emoji(polarity: str) -> str:
    """Return the Discord emoji string for a polarity name.  Falls back to the name itself."""
    return _data().get("emojis", {}).get(polarity.lower(), polarity)


def display(polarity: str) -> str:
    """Return  '<emoji> <name>'  for display in embeds."""
    p = polarity.lower()
    return f"{emoji(p)} {p.capitalize()}"


# ─────────────────────────────────────────────────────────────────────────────
# Core cost calculation
# ─────────────────────────────────────────────────────────────────────────────

def adjusted_drain(
    base_drain:   int,
    slot_polarity: str,
    mod_polarity:  str,
) -> int:
    """
    Return the effective drain cost after applying polarity rules.

    Args:
        base_drain:    The mod's base drain value (already at desired rank).
        slot_polarity: The polarity of the equip slot ("madurai", "any", …).
        mod_polarity:  The polarity of the mod being equipped.

    Returns:
        Adjusted drain (always ≥ 1).

    Wiki rules:
        match   → ceil(base_drain / 2)
        neutral → base_drain
        mismatch→ base_drain * 2
    """
    sp = slot_polarity.lower()
    mp = mod_polarity.lower()

    # Either side is "any" → neutral
    if sp == ANY or mp == ANY:
        return max(1, base_drain)

    if sp == mp:
        return max(1, math.ceil(base_drain / 2))

    return max(1, base_drain * 2)


def polarity_tag(
    slot_polarity: str,
    mod_polarity:  str,
) -> str:
    """
    Return a short human-readable tag describing the polarity match state.
    Used in embed footers.

        "✅ Match"  /  "⚪ Neutral"  /  "❌ Mismatch"
    """
    sp = slot_polarity.lower()
    mp = mod_polarity.lower()

    if sp == ANY or mp == ANY:
        return "⚪ Neutral"
    if sp == mp:
        return "✅ Match (half cost)"
    return "❌ Mismatch (double cost)"


# ─────────────────────────────────────────────────────────────────────────────
# Slot / mod polarity lookup helpers
# ─────────────────────────────────────────────────────────────────────────────

def warframe_slot_polarities(warframe_key: str) -> list[str]:
    """Return the list of warframe mod-slot polarities for a given Warframe."""
    wf = _data().get("warframes", {}).get(warframe_key.lower(), {})
    return wf.get("warframe_slots", [ANY] * 8)


def weapon_slot_polarities(weapon_name: str, slot_type: str = "primary") -> list[str]:
    """
    Return the mod-slot polarities for a weapon.

    Args:
        weapon_name: Display name, e.g. "MK1-Braton".
        slot_type:   One of "primary" | "secondary" | "melee".
                     Used only when weapon data is looked up from warframe slots;
                     for weapon-keyed data the slot_type is ignored.
    """
    wpn = _data().get("weapons", {}).get(weapon_name, {})
    return wpn.get("slots", [ANY] * 8)


def mod_polarity(mod_name: str) -> str:
    """Return the polarity of a named mod.  Defaults to 'any' if not found."""
    return _data().get("mods", {}).get(mod_name, ANY)


# ─────────────────────────────────────────────────────────────────────────────
# Equipped-mod capacity helper
# ─────────────────────────────────────────────────────────────────────────────

def capacity_summary(
    base_capacity: int,
    slots: list[str],
    equipped: list[tuple[str, int]],   # [(mod_name, base_drain), ...]
) -> dict:
    """
    Calculate the total used / remaining capacity for a set of equipped mods.

    Args:
        base_capacity: Unmodded slot capacity (e.g. 60 at max rank in game;
                       use a sensible TB value — we use 30 by default).
        slots:         Ordered list of slot polarity strings.
        equipped:      List of (mod_name, base_drain) tuples in slot order.
                       Pass ("", 0) for empty slots.

    Returns:
        {
          "capacity":  int,        # base capacity
          "used":      int,        # total adjusted drain
          "remaining": int,        # capacity - used (may be negative = over)
          "over":      bool,       # True if used > capacity
          "slots": [               # per-slot detail
            {
              "index":        int,
              "slot_polarity": str,
              "mod_name":     str | None,
              "mod_polarity": str | None,
              "base_drain":   int,
              "adj_drain":    int,
              "tag":          str,
            }, …
          ]
        }
    """
    slot_details = []
    total_used = 0

    for i, slot_pol in enumerate(slots):
        if i < len(equipped):
            mod_name, base_drain = equipped[i]
        else:
            mod_name, base_drain = "", 0

        if mod_name:
            mp      = mod_polarity(mod_name)
            adj     = adjusted_drain(base_drain, slot_pol, mp)
            tag     = polarity_tag(slot_pol, mp)
            total_used += adj
        else:
            mp = None
            adj = 0
            tag = "—"

        slot_details.append({
            "index":         i,
            "slot_polarity": slot_pol,
            "mod_name":      mod_name or None,
            "mod_polarity":  mp,
            "base_drain":    base_drain,
            "adj_drain":     adj,
            "tag":           tag,
        })

    return {
        "capacity":  base_capacity,
        "used":      total_used,
        "remaining": base_capacity - total_used,
        "over":      total_used > base_capacity,
        "slots":     slot_details,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: build a compact slot-polarity display string
# ─────────────────────────────────────────────────────────────────────────────

def slots_display(slot_polarities: list[str]) -> str:
    """
    Return a compact string of slot-polarity emojis for use in embeds.
    e.g.  "<:madurai:…> <:naramon:…> <:any:…> <:any:…>"
    """
    return "  ".join(emoji(p) for p in slot_polarities)
