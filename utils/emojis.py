"""
utils/emojis.py
─────────────────────────────────────────────────────────────────────────────
Central emoji asset manager.  All bot files import E from here.

Flat attribute access:
    from utils.emojis import E
    E.lotus          →  "<:wf_lotus:1499651243101126816>"
    E.credits        →  "<:credits:1499637105142399087>"
    E.slash          →  "<:slash_effect:1499584690859020459>"
    E.common         →  "<:common:1499767200410636351>"

Typed lookup helpers:
    E.mod("Vitality")        →  mod icon, rarity fallback if unknown
    E.mod("Vitality", "common")
    E.rarity("uncommon")     →  rarity-tier icon
    E.warframe("excalibur")  →  warframe portrait icon
    E.weapon("braton")       →  weapon icon
    E.enemy("grineer_lancer")→  enemy icon
    E.item("ferrite")        →  item/resource icon

All emoji IDs live in data/emojis.json.  Edit that file to update any emoji.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
from typing import Optional

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "emojis.json")
_cache: dict = {}


def _data() -> dict:
    global _cache
    if not _cache:
        with open(_DATA_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


class _EmojiManager:
    """
    Provides flat attribute access across all emoji categories plus typed
    helper methods for context-specific lookups.
    """

    def __getattr__(self, key: str) -> str:
        d = _data()
        for section_key, section in d.items():
            if section_key.startswith("_"):
                continue
            if isinstance(section, dict) and key in section:
                return section[key]
        raise AttributeError(
            f"Emoji '{key}' not found in data/emojis.json. "
            f"Add it to the appropriate section."
        )

    def mod(self, name: str, rarity: str = "common") -> str:
        """Return the icon emoji for a mod by name.  Falls back to rarity tier."""
        icon = _data().get("mods", {}).get(name)
        if icon:
            return icon
        return _data().get("rarity", {}).get(rarity.lower(), "📦")

    def rarity(self, r: str) -> str:
        """Return the rarity-tier emoji for 'common' / 'uncommon' / 'rare'."""
        return _data().get("rarity", {}).get(r.lower(), "📦")

    def warframe(self, key: str) -> str:
        """Return the portrait icon for a warframe key (e.g. 'excalibur')."""
        return _data().get("warframes", {}).get(key.lower(), "❓")

    def weapon(self, key: str) -> str:
        """Return the icon for a weapon key (e.g. 'braton')."""
        return _data().get("weapons", {}).get(key.lower(), "⚔️")

    def enemy(self, key: str) -> str:
        """Return the icon for an enemy key (e.g. 'grineer_lancer')."""
        return _data().get("enemies", {}).get(key.lower(), "👾")

    def item(self, key: str) -> str:
        """Return the icon for a resource/item key (e.g. 'ferrite', 'Detonite Ampule')."""
        items = _data().get("items", {})
        normalized = key.lower().replace(" ", "_")
        return items.get(normalized) or items.get(key.lower(), "📦")

    def ability(self, key: str) -> str:
        """Return the icon for an ability key (e.g. 'slash_dash')."""
        return _data().get("abilities", {}).get(key.lower(), "✨")

    def damage(self, dtype: str) -> str:
        """Return the icon for a damage type (e.g. 'slash', 'electricity')."""
        return _data().get("damage", {}).get(dtype.lower(), "⚔️")

    def reload(self) -> None:
        """Force-reload emojis.json (useful after editing the file at runtime)."""
        global _cache
        _cache = {}


E = _EmojiManager()
