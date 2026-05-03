# combat/weapons.py
# ─────────────────────────────────────────────────────────────────────────────
# Combat-side weapon registry.
#
# WEAPON_STATS is keyed by the weapon's display name (e.g. "MK1-Braton").
# Every entry consumed by abilities.py / session.py / cogs/combat.py.
#
# Schema per weapon:
#   emoji           str   — Discord emoji for button label
#   action_label    str   — Short verb shown on the attack button
#   hits_per_action int   — Number of hit rolls per action
#   total_per_hit   float — Base damage per hit (before crit)
#   damage_per_hit  dict  — {dtype: fraction} sums to 1.0; drives proc rolls
#   crit_chance     float — 0.0–1.0
#   crit_mult       float — Multiplier on a critical hit
#   status_chance   float — 0.0–1.0 per hit
#   punch_through   bool  — True → hits ALL living enemies in a line
#   silent          bool  — True → never alerts nearby enemies
#   excalibur_bonus float — Extra damage mult when Excalibur wields this
#                           (non-zero only for melee swords)
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import random


WEAPON_STATS: dict[str, dict] = {

    # ── PRIMARY — MK1-BRATON ──────────────────────────────────────────────────
    # Wiki: 7.92 Impact / 7.92 Puncture / 8.16 Slash = 24 per bullet.
    # TB:   3 hits per action (burst fire).  6% status/hit, 12% crit/hit.
    "MK1-Braton": {
        "emoji":          "<:braton:1499699815813218325>",
        "action_label":   "Burst Fire",
        "hits_per_action": 3,
        "total_per_hit":  24.0,
        "damage_per_hit": {
            "impact":   0.33,
            "puncture": 0.33,
            "slash":    0.34,
        },
        "crit_chance":    0.12,
        "crit_mult":      1.6,
        "status_chance":  0.06,
        "punch_through":  False,
        "silent":         False,
        "excalibur_bonus": 0.0,
    },

    # ── PRIMARY — PARIS ───────────────────────────────────────────────────────
    # Wiki: Impact 16, Puncture 256, Slash 48 = 320 total.
    # TB:   1 arrow per action.  Punch-Through on all enemies in line.
    "Paris": {
        "emoji":          "<:paris:1499699912445661214>",
        "action_label":   "Draw & Fire",
        "hits_per_action": 1,
        "total_per_hit":  320.0,
        "damage_per_hit": {
            "impact":   0.05,
            "puncture": 0.80,
            "slash":    0.15,
        },
        "crit_chance":    0.30,
        "crit_mult":      2.0,
        "status_chance":  0.10,
        "punch_through":  True,
        "silent":         True,
        "excalibur_bonus": 0.0,
    },

    # ── SECONDARY — LATO ──────────────────────────────────────────────────────
    # Wiki: Impact 10, Puncture 10, Slash 20 = 40 total.
    # TB:   1 shot per action.
    "Lato": {
        "emoji":          "<:lato:1499699965109207051>",
        "action_label":   "Quick Shot",
        "hits_per_action": 1,
        "total_per_hit":  40.0,
        "damage_per_hit": {
            "impact":   0.25,
            "puncture": 0.25,
            "slash":    0.50,
        },
        "crit_chance":    0.10,
        "crit_mult":      1.5,
        "status_chance":  0.10,
        "punch_through":  False,
        "silent":         False,
        "excalibur_bonus": 0.0,
    },

    # ── SECONDARY — KUNAI ─────────────────────────────────────────────────────
    # Wiki: Impact 7.5, Puncture 22.5, Slash 15 = 45 total.  Silent.
    # TB:   1 throw per action.  High status chance.
    "Kunai": {
        "emoji":          "<:kunai:1499920860344094830>",
        "action_label":   "Throw",
        "hits_per_action": 1,
        "total_per_hit":  45.0,
        "damage_per_hit": {
            "impact":   0.17,
            "puncture": 0.50,
            "slash":    0.33,
        },
        "crit_chance":    0.05,
        "crit_mult":      1.5,
        "status_chance":  0.15,
        "punch_through":  False,
        "silent":         True,
        "excalibur_bonus": 0.0,
    },

    # ── MELEE — SKANA ─────────────────────────────────────────────────────────
    # Wiki: Impact 18, Puncture 18, Slash 84 = 120 total.
    # TB:   1 swing per action.  Slash-dominant → bypasses armor.
    #       Excalibur passive: +10% damage.
    "Skana": {
        "emoji":          "<:skana:1499700067672526899>",
        "action_label":   "Slash",
        "hits_per_action": 1,
        "total_per_hit":  120.0,
        "damage_per_hit": {
            "impact":   0.15,
            "puncture": 0.15,
            "slash":    0.70,
        },
        "crit_chance":    0.05,
        "crit_mult":      1.5,
        "status_chance":  0.16,
        "punch_through":  False,
        "silent":         False,
        "excalibur_bonus": 0.10,   # Excalibur passive
    },

    # ── MELEE — BO ────────────────────────────────────────────────────────────
    # Wiki: Impact 42, Puncture 8.4, Slash 9.6 = 60 total.
    # TB:   Scaled to 100 total.  Impact-dominant → Knockdown proc.
    "Bo": {
        "emoji":          "<:bo_staff:1499920804866031797>",
        "action_label":   "Strike",
        "hits_per_action": 1,
        "total_per_hit":  100.0,
        "damage_per_hit": {
            "impact":   0.70,
            "puncture": 0.14,
            "slash":    0.16,
        },
        "crit_chance":    0.05,
        "crit_mult":      1.5,
        "status_chance":  0.10,
        "punch_through":  False,
        "silent":         False,
        "excalibur_bonus": 0.0,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Shared combat helpers
# ─────────────────────────────────────────────────────────────────────────────

def roll_crit(base_damage: float, crit_chance: float, crit_mult: float) -> tuple[float, bool]:
    """
    Roll a critical hit.

    Args:
        base_damage:  Pre-crit damage value.
        crit_chance:  0.0–1.0 probability of a crit.
        crit_mult:    Damage multiplier on a crit.

    Returns:
        (final_damage, is_crit)
    """
    if random.random() < crit_chance:
        return base_damage * crit_mult, True
    return base_damage, False


def weighted_proc_type(damage_per_hit: dict[str, float]) -> str:
    """
    Randomly select a damage type weighted by its fraction in damage_per_hit.

    Args:
        damage_per_hit: {dtype: fraction} dict — fractions should sum to ~1.0.

    Returns:
        A damage type string, e.g. "slash", "impact", "puncture".
    """
    types   = list(damage_per_hit.keys())
    weights = list(damage_per_hit.values())
    return random.choices(types, weights=weights, k=1)[0]
