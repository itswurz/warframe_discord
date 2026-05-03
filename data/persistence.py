# data/persistence.py
# ─────────────────────────────────────────────────────────────────────────────
# Termux-safe, async-safe JSON player persistence + global state.
#
# Storage layout:
#   ./data/players/{user_id}.json   — per-player profile
#   ./data/global_state.json        — server-wide leaderboard, economy, events
#   ./data/cache/                   — reserved
#
# Player profile schema (v6):
#   mod_collection entries:
#     "uuid":                  str   — 7-char alphanumeric ID, e.g. "A9X4M2Q"
#     "name":                  str
#     "rarity":                str   — "common" | "uncommon" | "rare"
#     "rank":                  int   — 0..max_rank
#     "max_rank":              int   — pulled from codex on mint
#     "acquired_at":           str   — ISO-8601 UTC
#     "source":                str   — e.g. "drop:grineer_lancer"
#     "tradeable":             bool  — False when equipped
#     "equipped_on_warframe":  str | None
#
# Warframe roster entry schema (unchanged):
#   "instance_id":   7-char alphanumeric
#   "equipped_mods": {slot_idx_str: {mod_uuid, mod_name, codex_uuid} | null}
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import glob
import json
import os
import asyncio
import random
import string
from datetime import datetime, timezone
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
PLAYERS_DIR        = "./data/players"
CACHE_DIR          = "./data/cache"
GLOBAL_STATE_PATH  = "./data/global_state.json"

SCHEMA_VERSION_PLAYER = 6   # bumped: 7-char mod UUIDs + rank/max_rank fields
SCHEMA_VERSION_GLOBAL = 1

MAX_WARFRAME_SLOTS = 3

# ── Fusion cost engine (official wiki formulas) ───────────────────────────────
# Source: https://wiki.warframe.com/w/Fusion  and  https://wiki.warframe.com/w/Endo
#
# Endo:
#   EBC (Endo Base Cost): common=10, uncommon=20, rare=30
#   Cost to go from rank N to rank N+1 = EBC × 2^N
#   e.g. common rank 0→1 = 10, 1→2 = 20, ..., 9→10 = 5,120; total = 10,230
#
# Credits:
#   CrBC (Credit Base Cost): common=483, uncommon=966, rare=1449
#   Cost to go from rank N to rank N+1 = CrBC × 2^N
#   e.g. common rank 0→1 = 483, ..., 9→10 = 247,296; total = 494,109

_EBC: dict[str, int] = {"common": 10, "uncommon": 20, "rare": 30}
_CRBC: dict[str, int] = {"common": 483, "uncommon": 966, "rare": 1449}

# Fallback precomputed lists (for callers that don't know rarity, keyed by max_rank)
# Uses common EBC for simplicity — most codex mods specify rarity explicitly.
_ENDO_COSTS_COMMON: dict[int, list[int]] = {
    5:  [10, 20, 40, 80, 160],
    10: [10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120],
    0:  [],
}


def _endo_ebc(rarity: str) -> int:
    """Return the Endo Base Cost for a given rarity string."""
    return _EBC.get(rarity.lower(), 10)


def _credit_crbc(rarity: str) -> int:
    """Return the Credit Base Cost for a given rarity string."""
    return _CRBC.get(rarity.lower(), 483)


def endo_cost_per_rank(rarity: str, target_rank: int) -> int:
    """
    Endo cost to advance from rank (target_rank-1) to target_rank.
    target_rank must be ≥ 1.
    Formula: EBC × 2^(target_rank - 1)
    """
    if target_rank < 1:
        return 0
    return _endo_ebc(rarity) * (2 ** (target_rank - 1))


def credit_cost_per_rank(rarity: str, target_rank: int) -> int:
    """
    Credit cost to advance from rank (target_rank-1) to target_rank.
    target_rank must be ≥ 1.
    Formula: CrBC × 2^(target_rank - 1)
    """
    if target_rank < 1:
        return 0
    return _credit_crbc(rarity) * (2 ** (target_rank - 1))


def endo_cost_to_rank(
    current_rank: int,
    target_rank:  int,
    max_rank:     int,
    rarity:       str = "common",
) -> int:
    """Sum of Endo needed to go from current_rank to target_rank."""
    total = 0
    for r in range(current_rank + 1, target_rank + 1):
        if r <= max_rank:
            total += endo_cost_per_rank(rarity, r)
    return total


def credit_cost_to_rank(
    current_rank: int,
    target_rank:  int,
    max_rank:     int,
    rarity:       str = "common",
) -> int:
    """Sum of Credits needed to go from current_rank to target_rank."""
    total = 0
    for r in range(current_rank + 1, target_rank + 1):
        if r <= max_rank:
            total += credit_cost_per_rank(rarity, r)
    return total


def endo_cost_next_rank(current_rank: int, max_rank: int, rarity: str = "common") -> int:
    """Endo cost to advance one rank (current → current+1)."""
    if current_rank >= max_rank:
        return 0
    return endo_cost_per_rank(rarity, current_rank + 1)


def credit_cost_next_rank(current_rank: int, max_rank: int, rarity: str = "common") -> int:
    """Credit cost to advance one rank (current → current+1)."""
    if current_rank >= max_rank:
        return 0
    return credit_cost_per_rank(rarity, current_rank + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Short ID generators (7-char alphanumeric)
# ─────────────────────────────────────────────────────────────────────────────

_ID_CHARS = string.ascii_uppercase + string.digits

def _generate_short_id() -> str:
    """Generate a 7-character uppercase alphanumeric ID, e.g. 'A9X4M2Q'."""
    return "".join(random.choices(_ID_CHARS, k=7))


def generate_warframe_id() -> str:
    return _generate_short_id()


def generate_mod_id(existing_ids: set[str] | None = None) -> str:
    """Generate a collision-free 7-char mod ID."""
    existing = existing_ids or set()
    for _ in range(200):
        new_id = _generate_short_id()
        if new_id not in existing:
            return new_id
    # Extremely unlikely fallback — extend to 9 chars
    return "".join(random.choices(_ID_CHARS, k=9))


def make_warframe_instance(
    warframe_key:  str,
    warframe_name: str,
    existing_ids:  set[str] | None = None,
    is_active:     bool = False,
) -> dict:
    existing = existing_ids or set()
    for _ in range(100):
        wf_id = _generate_short_id()
        if wf_id not in existing:
            break
    return {
        "instance_id":   wf_id,
        "warframe_key":  warframe_key,
        "warframe_name": warframe_name,
        "level":         0,
        "xp":            0,
        "acquired_at":   datetime.now(timezone.utc).isoformat(),
        "is_active":     is_active,
        "equipped_mods": {},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Schema defaults
# ─────────────────────────────────────────────────────────────────────────────

def _default_profile(user_id: int | str) -> dict:
    return {
        "schema_version":   SCHEMA_VERSION_PLAYER,
        "user_id":          str(user_id),
        "initialized":      False,
        "tutorial_step":    None,
        "current_quest":    None,
        "current_mission":  None,
        "completed_quests":   [],
        "completed_missions": [],
        "warframe":         None,
        "weapon":           None,
        "secondary_weapon": None,
        "melee_weapon":     None,
        "warframe_roster":  [],
        "warframe_level":   0,
        "mastery_rank":     0,
        "credits":          0,
        "platinum":         0,
        "experience":       0,
        "total_kills":      0,
        "total_missions":   0,
        "missions_won":     0,
        "missions_lost":    0,
        "highest_combo":    0,
        "damage_dealt":     0,
        "inventory": {},
        "mod_collection": [],
        "equipped_mods": {
            "primary_1":   None, "primary_2":   None,
            "secondary_1": None, "secondary_2": None,
            "melee_1":     None, "melee_2":     None,
            "warframe_1":  None, "warframe_2":  None,
        },
        "trade_history": [],
    }


def _default_global_state() -> dict:
    return {
        "schema_version":     SCHEMA_VERSION_GLOBAL,
        "total_missions":     0,
        "total_kills":        0,
        "credits_in_economy": 0,
        "leaderboard":        {},
        "active_events":      [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Mod instance factory
# ─────────────────────────────────────────────────────────────────────────────

def _get_codex_max_rank(name: str) -> int:
    """Look up max_rank from mods.json codex. Defaults to 5."""
    try:
        import json as _json
        _path = os.path.join(os.path.dirname(__file__), "mods.json")
        with open(_path, "r", encoding="utf-8") as f:
            _db = _json.load(f)
        name_l = name.lower()
        for mod_name, mod_data in _db.get("mods", {}).items():
            if mod_name.lower() == name_l:
                return mod_data.get("max_rank", 5)
    except Exception:
        pass
    return 5


def make_mod_instance(
    name:          str,
    rarity:        str,
    source:        str = "drop:unknown",
    existing_ids:  set[str] | None = None,
) -> dict:
    """
    Mint a new mod collection entry with a short 7-char UUID.
    """
    mod_uuid = generate_mod_id(existing_ids)
    max_rank = _get_codex_max_rank(name)
    return {
        "uuid":                 mod_uuid,
        "name":                 name,
        "rarity":               rarity,
        "rank":                 1,
        "max_rank":             max_rank,
        "acquired_at":          datetime.now(timezone.utc).isoformat(),
        "source":               source,
        "tradeable":            True,
        "equipped_on_warframe": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Inventory helpers
# ─────────────────────────────────────────────────────────────────────────────

def add_to_inventory(profile: dict, name: str, amount: int = 1) -> None:
    inv = profile.setdefault("inventory", {})
    inv[name] = inv.get(name, 0) + amount


def remove_from_inventory(profile: dict, name: str, amount: int = 1) -> bool:
    inv  = profile.get("inventory", {})
    have = inv.get(name, 0)
    if have < amount:
        return False
    inv[name] = have - amount
    if inv[name] == 0:
        del inv[name]
    return True


def get_mod_by_uuid(profile: dict, mod_uuid: str) -> Optional[dict]:
    for mod in profile.get("mod_collection", []):
        if mod["uuid"] == mod_uuid:
            return mod
    return None


def remove_mod_by_uuid(profile: dict, mod_uuid: str) -> Optional[dict]:
    collection = profile.get("mod_collection", [])
    for i, mod in enumerate(collection):
        if mod["uuid"] == mod_uuid:
            removed = collection.pop(i)
            for slot, equipped_uuid in profile.get("equipped_mods", {}).items():
                if equipped_uuid == mod_uuid:
                    profile["equipped_mods"][slot] = None
            for wf in profile.get("warframe_roster", []):
                em = wf.get("equipped_mods", {})
                for s_key, s_data in em.items():
                    if s_data and s_data.get("mod_uuid") == mod_uuid:
                        em[s_key] = None
                        break
            return removed
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Warframe-scoped mod helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_wf_instance_by_id(profile: dict, instance_id: str) -> Optional[dict]:
    inst_upper = instance_id.upper()
    for wf in profile.get("warframe_roster", []):
        if wf.get("instance_id", "").upper() == inst_upper:
            return wf
    return None


def free_all_mods_from_warframe(profile: dict, wf_instance: dict) -> int:
    em    = wf_instance.get("equipped_mods", {})
    freed = 0
    for s_key, s_data in list(em.items()):
        if not s_data:
            continue
        mod_uuid = s_data.get("mod_uuid", "")
        mod_inst = get_mod_by_uuid(profile, mod_uuid)
        if mod_inst:
            mod_inst["equipped_on_warframe"] = None
            mod_inst["tradeable"]            = True
        em[s_key] = None
        freed += 1
    wf_instance["equipped_mods"] = em
    return freed


# ─────────────────────────────────────────────────────────────────────────────
# Warframe roster helpers
# ─────────────────────────────────────────────────────────────────────────────

def roster_instance_ids(profile: dict) -> set[str]:
    return {wf["instance_id"] for wf in profile.get("warframe_roster", [])}


def get_active_warframe_instance(profile: dict) -> Optional[dict]:
    for wf in profile.get("warframe_roster", []):
        if wf.get("is_active"):
            return wf
    return None


def set_active_warframe(profile: dict, instance_id: str) -> bool:
    found = False
    for wf in profile.get("warframe_roster", []):
        if wf["instance_id"] == instance_id:
            wf["is_active"] = True
            profile["warframe"] = wf["warframe_name"]
            found = True
        else:
            wf["is_active"] = False
    return found


def add_warframe_to_roster(
    profile:       dict,
    warframe_key:  str,
    warframe_name: str,
    set_active:    bool = False,
) -> Optional[dict]:
    roster = profile.setdefault("warframe_roster", [])
    if len(roster) >= MAX_WARFRAME_SLOTS:
        return None

    existing_ids = roster_instance_ids(profile)
    instance = make_warframe_instance(
        warframe_key  = warframe_key,
        warframe_name = warframe_name,
        existing_ids  = existing_ids,
        is_active     = set_active,
    )

    if set_active:
        for wf in roster:
            wf["is_active"] = False
        profile["warframe"] = warframe_name

    roster.append(instance)
    return instance


def remove_warframe_from_roster(
    profile:     dict,
    instance_id: str,
) -> Optional[dict]:
    roster     = profile.get("warframe_roster", [])
    target     = None
    target_idx = -1

    for i, wf in enumerate(roster):
        if wf["instance_id"] == instance_id:
            target     = wf
            target_idx = i
            break

    if target is None or target_idx == -1:
        return None

    free_all_mods_from_warframe(profile, target)
    roster.pop(target_idx)
    profile["warframe_roster"] = roster

    was_active = target.get("is_active", False)
    if was_active and roster:
        roster[0]["is_active"] = True
        profile["warframe"]    = roster[0]["warframe_name"]
    elif not roster:
        profile["warframe"] = None

    return target


# ─────────────────────────────────────────────────────────────────────────────
# Cross-player Warframe lookup
# ─────────────────────────────────────────────────────────────────────────────

async def find_warframe_by_instance_id(
    instance_id: str,
) -> tuple[str | None, dict | None]:
    return await asyncio.to_thread(
        _find_warframe_by_instance_id_sync,
        instance_id.upper(),
    )


def _find_warframe_by_instance_id_sync(
    instance_id_upper: str,
) -> tuple[str | None, dict | None]:
    _ensure_dirs()
    pattern = os.path.join(PLAYERS_DIR, "*.json")

    for path in glob.glob(pattern):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        for wf in data.get("warframe_roster", []):
            if wf.get("instance_id", "").upper() == instance_id_upper:
                user_id = os.path.splitext(os.path.basename(path))[0]
                return user_id, wf

    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Cross-player mod lookup (by UUID)
# ─────────────────────────────────────────────────────────────────────────────

async def find_mod_by_uuid(
    mod_uuid: str,
) -> tuple[str | None, dict | None]:
    """Scan all player files for a mod with the given UUID.
    Returns (owner_user_id_str, mod_instance_dict) or (None, None)."""
    return await asyncio.to_thread(_find_mod_by_uuid_sync, mod_uuid.upper())


def _find_mod_by_uuid_sync(uuid_upper: str) -> tuple[str | None, dict | None]:
    _ensure_dirs()
    for path in glob.glob(os.path.join(PLAYERS_DIR, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for m in data.get("mod_collection", []):
            if m.get("uuid", "").upper() == uuid_upper:
                user_id = os.path.splitext(os.path.basename(path))[0]
                return user_id, m
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Stat helpers
# ─────────────────────────────────────────────────────────────────────────────

def record_mission_result(
    profile:        dict,
    victory:        bool,
    kills:          int,
    damage_dealt:   int,
    combo_reached:  int,
    credits_earned: int,
) -> None:
    profile["total_missions"] += 1
    profile["total_kills"]    += kills
    profile["damage_dealt"]   += damage_dealt
    profile["credits"]        += credits_earned

    if victory:
        profile["missions_won"]  += 1
    else:
        profile["missions_lost"] += 1

    if combo_reached > profile.get("highest_combo", 0):
        profile["highest_combo"] = combo_reached


# ─────────────────────────────────────────────────────────────────────────────
# Directory + path helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    os.makedirs(PLAYERS_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR,   exist_ok=True)
    if not os.path.exists(GLOBAL_STATE_PATH):
        _save_global_sync(_default_global_state())


def _player_path(user_id: int | str) -> str:
    return os.path.join(PLAYERS_DIR, f"{user_id}.json")


# ─────────────────────────────────────────────────────────────────────────────
# Schema migration
# ─────────────────────────────────────────────────────────────────────────────

def _migrate_player(data: dict) -> dict:
    default = _default_profile(data.get("user_id", "0"))

    for key, val in default.items():
        data.setdefault(key, val)

    data.setdefault("inventory",        {})
    data.setdefault("mod_collection",   [])
    data.setdefault("equipped_mods",    default["equipped_mods"])
    data.setdefault("trade_history",    [])
    data.setdefault("warframe_roster",  [])
    data.setdefault("initialized",      False)

    # v3 → v4: synthesise roster entry if player has a warframe but no roster.
    # Only run for already-initialized players — tutorial players have "warframe"
    # set before completing initialization and must not be affected here.
    if data.get("warframe") and not data["warframe_roster"] and data.get("initialized", False):
        wf_name = data["warframe"]
        try:
            from data.warframes import WARFRAMES
            wf_key = next(
                (k for k, v in WARFRAMES.items() if v["name"] == wf_name),
                wf_name.lower(),
            )
        except Exception:
            wf_key = wf_name.lower()

        instance = make_warframe_instance(
            warframe_key  = wf_key,
            warframe_name = wf_name,
            is_active     = True,
        )
        data["warframe_roster"].append(instance)
        data["initialized"] = True

    # v4/v5 → v6: migrate old UUID4 mod UUIDs to short IDs & add max_rank
    existing_short_ids: set[str] = set()
    for m in data.get("mod_collection", []):
        # Back-fill max_rank
        m.setdefault("max_rank", _get_codex_max_rank(m.get("name", "")))
        m.setdefault("equipped_on_warframe", None)
        m.setdefault("tradeable", True)

        # If UUID looks like a UUID4 (contains hyphens), replace with short ID
        current_uuid = m.get("uuid", "")
        if "-" in current_uuid or len(current_uuid) > 9:
            new_uuid = generate_mod_id(existing_short_ids)
            # Update any equipped_mods references that point to old UUID
            for wf in data.get("warframe_roster", []):
                em = wf.get("equipped_mods", {})
                for sk, sd in em.items():
                    if sd and sd.get("mod_uuid") == current_uuid:
                        sd["mod_uuid"] = new_uuid
            for slot, val in data.get("equipped_mods", {}).items():
                if val == current_uuid:
                    data["equipped_mods"][slot] = new_uuid
            m["uuid"] = new_uuid
            existing_short_ids.add(new_uuid)
        else:
            existing_short_ids.add(current_uuid)

    # v4 → v5: ensure every warframe roster entry has equipped_mods dict
    for wf in data.get("warframe_roster", []):
        wf.setdefault("equipped_mods", {})

    data.setdefault("secondary_weapon",  None)
    data.setdefault("melee_weapon",      None)
    data.setdefault("tutorial_step",      None)
    data.setdefault("current_quest",      None)
    data.setdefault("current_mission",    None)
    data.setdefault("completed_quests",   [])
    data.setdefault("completed_missions", [])

    data["schema_version"] = SCHEMA_VERSION_PLAYER
    return data


def _migrate_global(data: dict) -> dict:
    default = _default_global_state()
    for key, val in default.items():
        data.setdefault(key, val)
    data["schema_version"] = SCHEMA_VERSION_GLOBAL
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Sync I/O
# ─────────────────────────────────────────────────────────────────────────────

import json  # already used above, needed here too

def _load_player_sync(user_id: int | str) -> dict:
    _ensure_dirs()
    path = _player_path(user_id)
    if not os.path.exists(path):
        return _default_profile(user_id)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _migrate_player(data)


def _save_player_sync(profile: dict) -> None:
    _ensure_dirs()
    path = _player_path(profile["user_id"])
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _load_global_sync() -> dict:
    _ensure_dirs()
    if not os.path.exists(GLOBAL_STATE_PATH):
        return _default_global_state()
    with open(GLOBAL_STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _migrate_global(data)


def _save_global_sync(state: dict) -> None:
    os.makedirs(os.path.dirname(GLOBAL_STATE_PATH), exist_ok=True)
    tmp = GLOBAL_STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, GLOBAL_STATE_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# Public async API — Player
# ─────────────────────────────────────────────────────────────────────────────

async def load_player(user_id: int | str) -> dict:
    return await asyncio.to_thread(_load_player_sync, user_id)


async def save_player(profile: dict) -> None:
    await asyncio.to_thread(_save_player_sync, profile)


async def set_warframe(user_id: int | str, warframe_name: str) -> dict:
    profile = await load_player(user_id)
    profile["warframe"] = warframe_name
    await save_player(profile)
    return profile


async def set_weapon(user_id: int | str, weapon_name: str) -> dict:
    profile = await load_player(user_id)
    profile["weapon"] = weapon_name
    await save_player(profile)
    return profile


async def add_mod_to_collection(
    user_id: int | str,
    name:    str,
    rarity:  str,
    source:  str = "drop:unknown",
) -> dict:
    profile = await load_player(user_id)
    existing_ids = {m["uuid"] for m in profile.get("mod_collection", [])}
    mod = make_mod_instance(name, rarity, source, existing_ids)
    profile["mod_collection"].append(mod)
    await save_player(profile)
    return mod


async def equip_mod(
    user_id:  int | str,
    mod_uuid: str,
    slot:     str,
) -> tuple[bool, str]:
    profile = await load_player(user_id)
    mod     = get_mod_by_uuid(profile, mod_uuid)
    if mod is None:
        return False, f"Mod `{mod_uuid}` not found in your collection."
    slots = profile.get("equipped_mods", {})
    if slot not in slots:
        return False, f"Unknown slot `{slot}`."
    old_uuid = slots[slot]
    if old_uuid:
        old_mod = get_mod_by_uuid(profile, old_uuid)
        if old_mod:
            old_mod["tradeable"] = True
    slots[slot]      = mod_uuid
    mod["tradeable"] = False
    await save_player(profile)
    return True, f"**{mod['name']}** equipped in slot `{slot}`."


async def unequip_mod(user_id: int | str, slot: str) -> tuple[bool, str]:
    profile = await load_player(user_id)
    slots   = profile.get("equipped_mods", {})
    if slot not in slots:
        return False, f"Unknown slot `{slot}`."
    mod_uuid = slots[slot]
    if mod_uuid is None:
        return False, f"Slot `{slot}` is already empty."
    mod = get_mod_by_uuid(profile, mod_uuid)
    if mod:
        mod["tradeable"] = True
    slots[slot] = None
    await save_player(profile)
    return True, f"Slot `{slot}` cleared."


# ─────────────────────────────────────────────────────────────────────────────
# Public async API — Global State
# ─────────────────────────────────────────────────────────────────────────────

async def load_global_state() -> dict:
    return await asyncio.to_thread(_load_global_sync)


async def save_global_state(state: dict) -> None:
    await asyncio.to_thread(_save_global_sync, state)


async def update_global_after_mission(
    user_id:  int | str,
    profile:  dict,
    kills:    int,
    victory:  bool,
) -> None:
    state = await load_global_state()
    state["total_missions"]     += 1
    state["total_kills"]        += kills
    state["leaderboard"][str(user_id)] = {
        "kills":        profile["total_kills"],
        "missions_won": profile["missions_won"],
        "mastery_rank": profile["mastery_rank"],
        "warframe":     profile.get("warframe") or "—",
    }
    await save_global_state(state)


async def get_leaderboard(top_n: int = 10) -> list[tuple[str, dict]]:
    state = await load_global_state()
    board = state.get("leaderboard", {})
    sorted_entries = sorted(
        board.items(),
        key=lambda x: x[1].get("kills", 0),
        reverse=True,
    )
    return sorted_entries[:top_n]
