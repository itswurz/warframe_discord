# data/global_state.py
# ─────────────────────────────────────────────────────────────────────────────
# Server-wide state and all cross-session persistence logic.
#
# Responsibilities
# ────────────────
#   1. GLOBAL STATE  (./data/global_state.json)
#         Server-wide counters, leaderboard snapshot, economy tracker,
#         and future event hooks.
#
#   2. SESSION → PROFILE COMMIT  (commit_session_to_profile)
#         After every mission (victory or defeat) this is the single call
#         that writes every relevant value back to the player profile:
#           • HP / Shields / Armor / Energy (live combat values)
#           • Combo gauge, static charges, ability toggle states
#           • Status effects (serialized as plain dicts, restored on load)
#           • Primary weapon choice
#           • Warframe key + name
#           • Mission statistics (kills, damage, highest combo, credits)
#           • Inventory: all stackable drops (resources, Endo, cosmetics)
#           • Mod collection: all UUID mod instances from drops
#
#   3. PLAYER PROFILE SNAPSHOT  (snapshot_warframe_state)
#         Serializes a WarframeEntity's live state into a plain dict so it
#         can be stored inside the player profile and later inspected without
#         re-instantiating the entity.  Used by the profile viewer cog.
#
#   4. LEADERBOARD HELPERS  (update_leaderboard, get_leaderboard)
#         Wrap the global state I/O from persistence.py with friendlier APIs.
#
# ─────────────────────────────────────────────────────────────────────────────
#
# File layout
# ───────────
#   global_state.json schema (v1):
#   {
#     "schema_version":     1,
#     "total_missions":     int,          # server-wide lifetime counter
#     "total_kills":        int,          # server-wide lifetime counter
#     "credits_in_economy": int,          # sum of all player credits ever earned
#
#     "leaderboard": {                    # keyed by user_id str
#       "<user_id>": {
#         "display_name":  str,           # Discord display name at time of update
#         "kills":         int,           # player lifetime kills
#         "missions_won":  int,
#         "missions_lost": int,
#         "mastery_rank":  int,
#         "warframe":      str,           # active Warframe display name
#         "weapon":        str,           # active Primary weapon display name
#         "credits":       int,
#         "damage_dealt":  int,
#         "highest_combo": int,
#         "last_seen":     str,           # ISO-8601 UTC
#       }
#     },
#
#     "active_events": []                 # reserved for future alert events
#   }
#
# ─────────────────────────────────────────────────────────────────────────────
#
#   player profile additions written by commit_session_to_profile():
#   {
#     ... (all existing profile fields from persistence.py) ...
#
#     "last_warframe_state": {            # snapshot of WarframeEntity at mission end
#       "warframe_key":      str,
#       "warframe_name":     str,
#       "hp":                int,
#       "max_hp":            int,
#       "shields":           int,
#       "max_shields":       int,
#       "armor":             int,
#       "base_armor":        int,
#       "energy":            int,
#       "max_energy":        int,
#       "combo_gauge":       int,
#       "static_charges":    int,         # Volt passive
#       "exalted_active":    bool,        # Excalibur ability 4 toggle
#       "magnetize_absorb":  bool,        # Mag ability 2 defensive mode
#       "magnetize_stored":  int,         # Mag absorbed damage
#       "speed_active":      bool,        # Volt ability 2 buff
#       "speed_turns":       int,
#       "statuses": [                     # list of active StatusEffect dicts
#         {
#           "name":        str,
#           "status_type": str,           # StatusType enum name, e.g. "SLASH_BLEED"
#           "duration":    int,
#           "magnitude":   float,
#           "source":      str,
#           "stacks":      int,
#           "data":        dict,
#         }, ...
#       ]
#     },
#
#     "last_session": {                   # session-level field effects at mission end
#       "turn":                       int,
#       "state":                      str,   # "victory" | "defeat" | "player_turn" …
#       "primary_weapon_name":        str,
#       "actions_used":               int,
#       "bonus_actions":              int,
#       "player_untargetable":        bool,
#       "electric_shield_active":     bool,
#       "electric_shield_turns":      int,
#       "electric_shield_stacks":     int,
#       "electric_shield_electrified":bool,
#       "magnetize_target_key":       str | None,  # enemy_key of magnetized target
#       "magnetize_turns":            int,
#       "polarize_shards_absorbed":   bool,
#       "mission_kills":              int,
#       "mission_damage_dealt":       int,
#       "mission_credits_earned":     int,
#     },
#
#     "last_mission_loot": [              # all drops from the last mission
#       {                                 # same shape as drop dicts in session.mission_loot
#         "name":   str,
#         "amount": int,
#         "emoji":  str,
#         "rarity": str,
#         "type":   str,                  # "mod" | "endo" | "resource" | "cosmetic"
#         # "mod_instance" is NOT stored here — it is committed to mod_collection instead
#       }, ...
#     ]
#   }
#
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from data import persistence
from data.persistence import (
    load_player,
    save_player,
    load_global_state,
    save_global_state,
    add_to_inventory,
    record_mission_result,
)

if TYPE_CHECKING:
    from combat.session import CombatSession
    from combat.entities import WarframeEntity


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Status-effect serialization helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_status(effect) -> dict:
    """
    Convert a StatusEffect dataclass instance to a plain JSON-safe dict.
    Uses the enum *name* (e.g. "SLASH_BLEED") so it survives import cycles.
    """
    return {
        "name":        effect.name,
        "status_type": effect.status_type.name,   # e.g. "SLASH_BLEED"
        "duration":    effect.duration,
        "magnitude":   effect.magnitude,
        "source":      effect.source,
        "stacks":      effect.stacks,
        "data":        effect.data,
    }


def _deserialize_status(raw: dict):
    """
    Reconstruct a StatusEffect from a plain dict (as stored in the profile).
    Returns None if the status_type name is not recognised (forward-compat).
    """
    from combat.status import StatusEffect, StatusType

    type_name = raw.get("status_type", "")
    try:
        stype = StatusType[type_name]
    except KeyError:
        return None   # unknown status — skip gracefully

    return StatusEffect(
        name        = raw["name"],
        status_type = stype,
        duration    = raw["duration"],
        magnitude   = raw.get("magnitude", 0.0),
        source      = raw.get("source", ""),
        stacks      = raw.get("stacks", 1),
        data        = raw.get("data", {}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2.  WarframeEntity snapshot
# ─────────────────────────────────────────────────────────────────────────────

def snapshot_warframe_state(player: "WarframeEntity") -> dict:
    """
    Serialize the full live state of a WarframeEntity into a plain dict.
    Every field that can change during combat is captured here.

    Stored under profile["last_warframe_state"].
    """
    return {
        # ── Identity ──────────────────────────────────────────────────────────
        "warframe_key":     player.warframe_key,
        "warframe_name":    player.name,

        # ── Core vitals ───────────────────────────────────────────────────────
        "hp":               player.hp,
        "max_hp":           player.max_hp,
        "shields":          player.shields,
        "max_shields":      player.max_shields,
        "armor":            player.armor,          # current (may be Corrosive-stripped)
        "base_armor":       player.base_armor,     # original unmodified value
        "energy":           player.energy,
        "max_energy":       player.max_energy,

        # ── Melee / combo ─────────────────────────────────────────────────────
        "combo_gauge":      player.combo_gauge,

        # ── Volt passive ──────────────────────────────────────────────────────
        "static_charges":   player.static_charges,

        # ── Excalibur ability toggles ─────────────────────────────────────────
        "exalted_active":   player.exalted_active,

        # ── Mag ability state ─────────────────────────────────────────────────
        "magnetize_absorb": player.magnetize_absorb,
        "magnetize_stored": player.magnetize_stored,

        # ── Volt Speed buff ───────────────────────────────────────────────────
        "speed_active":     player.speed_active,
        "speed_turns":      player.speed_turns,

        # ── Active status effects (serialized) ────────────────────────────────
        "statuses": [_serialize_status(s) for s in player.statuses],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Session snapshot (field effects, turn counters)
# ─────────────────────────────────────────────────────────────────────────────

def snapshot_session_state(session: "CombatSession") -> dict:
    """
    Serialize all session-level field-effect flags and combat counters.

    Stored under profile["last_session"].
    This is informational — it is NOT reloaded to reconstruct a session,
    since mid-session persistence is not yet supported.  It exists so a
    profile viewer / stats cog can display what happened.
    """
    # Count kills from this mission
    kills = sum(
        1 for e in session.enemies
        if not e.is_alive
    )

    # Approximate damage dealt — sum of mission log is not tracked numerically,
    # so we pull it from the session's own accounting if available.
    # Falls back to 0; the caller may supply it via commit_session_to_profile().
    damage   = getattr(session, "_mission_damage_dealt", 0)
    credits  = getattr(session, "_mission_credits_earned", 0)

    mag_key = None
    if session.magnetize_target and not session.magnetize_target.is_alive:
        mag_key = None   # already dead — not meaningful to save
    elif session.magnetize_target:
        mag_key = session.magnetize_target.enemy_key

    return {
        # ── Turn / phase ──────────────────────────────────────────────────────
        "turn":                        session.turn,
        "state":                       session.state,
        "actions_used":                session.actions_used,
        "bonus_actions":               session.bonus_actions,

        # ── Weapon ────────────────────────────────────────────────────────────
        "primary_weapon_name":         session.primary_weapon_name,

        # ── Field effects ─────────────────────────────────────────────────────
        "player_untargetable":         session.player_untargetable,
        "electric_shield_active":      session.electric_shield_active,
        "electric_shield_turns":       session.electric_shield_turns,
        "electric_shield_stacks":      session.electric_shield_stacks,
        "electric_shield_electrified": session.electric_shield_electrified,
        "magnetize_target_key":        mag_key,
        "magnetize_turns":             session.magnetize_turns,
        "polarize_shards_absorbed":    session.polarize_shards_absorbed,

        # ── Mission outcome counters ───────────────────────────────────────────
        "mission_kills":               kills,
        "mission_damage_dealt":        damage,
        "mission_credits_earned":      credits,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Loot commit helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_loot_entry(drop: dict) -> dict:
    """
    Strip the 'mod_instance' key from a drop dict before storing it in
    profile["last_mission_loot"] — that key is a full UUID dict that must
    go into mod_collection instead, not into the loot log.
    """
    return {k: v for k, v in drop.items() if k != "mod_instance"}


def _commit_loot_to_profile(
    profile:      dict,
    mission_loot: list[dict],
    source_tag:   str,
) -> int:
    """
    Walk mission_loot and write each drop to the correct sub-store:
      • "mod"      → profile["mod_collection"]  (UUID instance already minted)
      • "endo"     → profile["inventory"]["Endo"]
      • "resource" → profile["inventory"][name]
      • "cosmetic" → profile["inventory"][name]

    Returns the number of mod instances added.
    """
    mods_added = 0

    for drop in mission_loot:
        dtype = drop["type"]
        name  = drop["name"]
        amt   = drop["amount"]

        if dtype == "mod":
            instance = drop.get("mod_instance")
            if instance:
                # Guarantee source tag is set (drops.py already sets it, but
                # defensive check here ensures nothing arrives as "drop:unknown")
                if instance.get("source", "drop:unknown") == "drop:unknown":
                    instance["source"] = source_tag
                profile["mod_collection"].append(instance)
                mods_added += 1

        elif dtype in ("endo", "resource", "cosmetic"):
            add_to_inventory(profile, name, amt)

    return mods_added


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Main commit entry point
# ─────────────────────────────────────────────────────────────────────────────

async def commit_session_to_profile(
    session:         "CombatSession",
    display_name:    str  = "",
    damage_dealt:    int  = 0,
    credits_earned:  int  = 0,
) -> dict:
    """
    Persist all combat results back to the player profile and the global state.

    Call this exactly ONCE after a mission ends (victory or defeat).
    cogs/combat._refresh() should await this instead of / in addition to
    any manual persistence calls.

    Args:
        session:        The completed CombatSession.
        display_name:   Discord display name (for leaderboard snapshot).
        damage_dealt:   Total damage dealt this mission (passed in from session
                        accounting — not currently summed inside session itself).
        credits_earned: Credits awarded for this mission outcome.

    Returns:
        The updated player profile dict (already saved to disk).
    """
    from combat.session import CombatState

    user_id    = session.user_id
    is_victory = session.state == CombatState.VICTORY
    player     = session.player

    # ── Store mission counters on session so snapshot picks them up ───────────
    kills = sum(1 for e in session.enemies if not e.is_alive)
    session._mission_damage_dealt    = damage_dealt
    session._mission_credits_earned  = credits_earned

    # ── Load profile ──────────────────────────────────────────────────────────
    profile = await load_player(user_id)

    # ── 1. Core loadout — always update from session truth ────────────────────
    profile["warframe"] = player.name
    profile["weapon"]   = session.primary_weapon_name

    # ── 2. Warframe state snapshot ────────────────────────────────────────────
    profile["last_warframe_state"] = snapshot_warframe_state(player)

    # ── 3. Session-level snapshot ─────────────────────────────────────────────
    profile["last_session"] = snapshot_session_state(session)

    # ── 4. Commit all loot drops to inventory + mod_collection ────────────────
    source_tag = f"drop:{player.warframe_key}_mission"
    _commit_loot_to_profile(profile, session.mission_loot, source_tag)

    # ── 5. Store a clean copy of the loot log (without mod_instance blobs) ────
    profile["last_mission_loot"] = [
        _safe_loot_entry(d) for d in session.mission_loot
    ]

    # ── 6. Mission statistics ─────────────────────────────────────────────────
    highest_combo = player.combo_gauge   # peak combo is at end; session could
                                         # track the max separately in future
    record_mission_result(
        profile        = profile,
        victory        = is_victory,
        kills          = kills,
        damage_dealt   = damage_dealt,
        combo_reached  = highest_combo,
        credits_earned = credits_earned,
    )

    # ── 7. Save player profile ────────────────────────────────────────────────
    await save_player(profile)

    # ── 8. Update global state ────────────────────────────────────────────────
    await _update_global(
        user_id      = user_id,
        profile      = profile,
        kills        = kills,
        display_name = display_name,
    )

    return profile


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Global state write
# ─────────────────────────────────────────────────────────────────────────────

async def _update_global(
    user_id:      int | str,
    profile:      dict,
    kills:        int,
    display_name: str = "",
) -> None:
    """
    Update server-wide counters and the leaderboard entry for this player.
    Internal — always called from commit_session_to_profile().
    """
    state = await load_global_state()

    # ── Server counters ───────────────────────────────────────────────────────
    state["total_missions"]     += 1
    state["total_kills"]        += kills
    state["credits_in_economy"] += profile.get("credits", 0)

    # ── Leaderboard snapshot ──────────────────────────────────────────────────
    # Kept small — no full profile dump.  Enough to render the top-10 embed.
    state["leaderboard"][str(user_id)] = {
        "display_name":  display_name or str(user_id),
        "kills":         profile["total_kills"],
        "missions_won":  profile["missions_won"],
        "missions_lost": profile["missions_lost"],
        "mastery_rank":  profile["mastery_rank"],
        "warframe":      profile.get("warframe") or "—",
        "weapon":        profile.get("weapon")   or "—",
        "credits":       profile.get("credits",   0),
        "damage_dealt":  profile.get("damage_dealt", 0),
        "highest_combo": profile.get("highest_combo", 0),
        "last_seen":     datetime.now(timezone.utc).isoformat(),
    }

    await save_global_state(state)


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Leaderboard read helpers
# ─────────────────────────────────────────────────────────────────────────────

async def get_leaderboard(
    sort_by: str = "kills",
    top_n:   int = 10,
) -> list[tuple[str, dict]]:
    """
    Return the top N leaderboard entries.

    Args:
        sort_by: One of "kills" | "missions_won" | "damage_dealt" |
                        "credits" | "highest_combo" | "mastery_rank".
                 Falls back to "kills" for unknown keys.
        top_n:   How many entries to return (default 10).

    Returns:
        List of (user_id_str, snapshot_dict) tuples, sorted descending.
    """
    state = await load_global_state()
    board = state.get("leaderboard", {})

    valid_keys = {
        "kills", "missions_won", "damage_dealt",
        "credits", "highest_combo", "mastery_rank",
    }
    key = sort_by if sort_by in valid_keys else "kills"

    sorted_entries = sorted(
        board.items(),
        key=lambda x: x[1].get(key, 0),
        reverse=True,
    )
    return sorted_entries[:top_n]


async def get_global_stats() -> dict:
    """
    Return the server-wide counters for a stats embed.

    Returns:
        {
          "total_missions":     int,
          "total_kills":        int,
          "credits_in_economy": int,
          "registered_players": int,
        }
    """
    state = await load_global_state()
    return {
        "total_missions":     state.get("total_missions",     0),
        "total_kills":        state.get("total_kills",        0),
        "credits_in_economy": state.get("credits_in_economy", 0),
        "registered_players": len(state.get("leaderboard",   {})),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8.  Status restore helper (future use — mid-session load)
# ─────────────────────────────────────────────────────────────────────────────

def restore_warframe_statuses(player: "WarframeEntity", profile: dict) -> None:
    """
    Re-apply serialized status effects from profile["last_warframe_state"]
    onto a freshly created WarframeEntity.

    Currently unused because sessions are not resumed across restarts.
    Placed here so the restoration logic lives next to the serialization logic.

    Usage:
        entity = WarframeEntity(key, data)
        restore_warframe_statuses(entity, profile)
    """
    state   = profile.get("last_warframe_state", {})
    raw_sts = state.get("statuses", [])

    for raw in raw_sts:
        effect = _deserialize_status(raw)
        if effect is not None:
            player.statuses.append(effect)
