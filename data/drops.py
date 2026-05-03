# data/drops.py
# ─────────────────────────────────────────────────────────────────────────────
# Rolls the loot table for a killed enemy and returns structured drop dicts.
#
# Public API:
#   roll_drops(enemy_key, source_tag) → list[dict]
#
# Each returned dict has one of two shapes:
#
#   STACKABLE DROP  (resource | endo | cosmetic):
#   {
#     "name":   str,
#     "amount": int,
#     "emoji":  str,
#     "rarity": str,
#     "type":   str,   # "resource" | "endo" | "cosmetic"
#   }
#
#   MOD DROP  (always has a UUID — call make_mod_instance() under the hood):
#   {
#     "name":   str,
#     "amount": 1,
#     "emoji":  str,
#     "rarity": str,
#     "type":   "mod",
#     "mod_instance": dict,   # ← full UUID mod dict from persistence.make_mod_instance()
#   }
#
# Integration with persistence:
#   session._collect_drops() must pass each mod drop's "mod_instance" dict
#   directly into profile["mod_collection"] and call save_player().
#   Stackable drops go through persistence.add_to_inventory().
#
# Drop logic:
#   • Mod / Endo table   — each entry rolled INDEPENDENTLY.
#   • Resources          — Common, Uncommon, Rare each independent.
#   • Region Resource    — bonus Ferrite roll at 7%.
#   • Cosmetics          — each entry rolled independently.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import os
import random

from data.persistence import make_mod_instance

_DROPS_PATH = os.path.join(os.path.dirname(__file__), "enemies.json")

# Module-level cache — reloaded only on import. Restart bot to pick up edits.
_CACHE: dict | None = None


def _data() -> dict:
    """Return a drops-compatible dict keyed by enemy key → flat drop fields."""
    global _CACHE
    if _CACHE is None:
        with open(_DROPS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        enemies_out: dict = {}
        for key, enemy in raw.get("enemies", {}).items():
            drops = enemy.get("drops", {})
            enemies_out[key] = {
                "mods":            drops.get("mods", []),
                "resources":       drops.get("resources", {}),
                "region_resource": drops.get("region_resource"),
                "cosmetics":       drops.get("cosmetics", []),
            }
        _CACHE = {"enemies": enemies_out}
    return _CACHE


def _emoji(name: str, rarity: str = "") -> str:
    """Return the display emoji for a drop item using the central emoji registry."""
    from utils.emojis import E
    icon = E.item(name)
    if icon != "📦":
        return icon
    return E.mod(name, rarity)


def roll_drops(
    enemy_key:  str,
    source_tag: str = "drop:unknown",
) -> list[dict]:
    """
    Roll the full loot table for one slain enemy.

    Args:
        enemy_key:  Key from enemies.json "enemies" section (e.g. "grineer_lancer").
        source_tag: Provenance string stored on mod instances, e.g.
                    "drop:grineer_lancer".  Defaults to "drop:unknown".

    Returns:
        A (possibly empty) list of drop dicts.  Mod drops include a
        "mod_instance" key containing the full UUID mod dict.
    """
    data  = _data()
    edata = data.get("enemies", {}).get(enemy_key)

    if not edata:
        return []

    # Build a sensible source tag if caller passed the generic default
    if source_tag == "drop:unknown" and enemy_key:
        source_tag = f"drop:{enemy_key}"

    drops: list[dict] = []

    # ── 1. Mod / Endo table ───────────────────────────────────────────────────
    for entry in edata.get("mods", []):
        if random.random() >= entry["chance"]:
            continue

        dtype  = entry.get("type", "mod")
        name   = entry["name"]
        amount = entry.get("amount", 1)
        rarity = entry.get("rarity", "common")
        em     = _emoji(name, rarity)

        if dtype == "endo":
            drops.append({
                "name":   "Endo",
                "amount": amount,
                "emoji":  em,
                "rarity": rarity,
                "type":   "endo",
            })
        else:
            # Mint a UUID mod instance on every mod drop
            mod_instance = make_mod_instance(name, rarity, source_tag)
            drops.append({
                "name":         name,
                "amount":       1,
                "emoji":        em,
                "rarity":       rarity,
                "type":         "mod",
                "mod_instance": mod_instance,   # ← carries the UUID
            })

    # ── 2. Resource tiers ─────────────────────────────────────────────────────
    res = edata.get("resources", {})

    common = res.get("common")
    if common and random.random() < common.get("chance", 0.80):
        amt = random.randint(common["min"], common["max"])
        drops.append({
            "name":   common["name"],
            "amount": amt,
            "emoji":  _emoji(common["name"]),
            "rarity": "common",
            "type":   "resource",
        })

    for item in res.get("uncommon", []):
        if random.random() >= item.get("chance", 0.20):
            continue
        amt = (
            random.randint(item["min"], item["max"])
            if "min" in item
            else item.get("amount", 1)
        )
        drops.append({
            "name":   item["name"],
            "amount": amt,
            "emoji":  _emoji(item["name"]),
            "rarity": "uncommon",
            "type":   "resource",
        })

    for item in res.get("rare", []):
        if random.random() >= item.get("chance", 0.03):
            continue
        drops.append({
            "name":   item["name"],
            "amount": item.get("amount", 1),
            "emoji":  _emoji(item["name"]),
            "rarity": "rare",
            "type":   "resource",
        })

    # ── 3. Region resource (bonus Ferrite roll) ───────────────────────────────
    region = edata.get("region_resource")
    if region and random.random() < region.get("chance", 0.07):
        amt = random.randint(region["min"], region["max"])
        drops.append({
            "name":   region["name"],
            "amount": amt,
            "emoji":  _emoji(region["name"]),
            "rarity": "common",
            "type":   "resource",
        })

    # ── 4. Cosmetics ──────────────────────────────────────────────────────────
    for item in edata.get("cosmetics", []):
        if random.random() >= item.get("chance", 0.50):
            continue
        drops.append({
            "name":   item["name"],
            "amount": item.get("amount", 1),
            "emoji":  _emoji(item["name"]),
            "rarity": "cosmetic",
            "type":   "cosmetic",
        })

    return drops
