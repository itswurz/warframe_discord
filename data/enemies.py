from __future__ import annotations
# data/enemies.py
# ─────────────────────────────────────────────────────────────────────────────
# Enemy codex loader — reads structural data from enemies.json and hydrates
# emoji references from utils.emojis.E so that the rest of the bot continues
# to receive ENEMIES dicts with a live "icon" field.
#
# Adding a new enemy: add it to data/enemies.json (no code changes needed here).
# ─────────────────────────────────────────────────────────────────────────────

import json
import os

from utils.emojis import E

_PATH = os.path.join(os.path.dirname(__file__), "enemies.json")

with open(_PATH, "r", encoding="utf-8") as _f:
    _raw = json.load(_f)


def _hydrate(key: str, entry: dict) -> dict:
    """Add a live 'icon' emoji field to an enemy entry."""
    out = dict(entry)
    icon_key = out.get("icon_key", key)
    out["icon"] = getattr(E, icon_key, "❓")
    return out


ENEMIES: dict[str, dict] = {
    k: _hydrate(k, v)
    for k, v in _raw.get("enemies", {}).items()
}

INTRO_ENCOUNTER: list[str] = _raw.get("intro_encounter", [])
