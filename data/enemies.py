from utils.emojis import E
# data/enemies.py
# ─────────────────────────────────────────────────────────────────────────────
# Enemy codex — Grineer & Corpus starter enemies adapted for turn-based combat.
# Source: Warframe Wiki (warframe.fandom.com)
#
# Turn-based adaptations applied:
#   • Distances removed — abilities reference "target" roles instead
#   • Stun durations explicit in turns, not seconds
#   • Abilities reduced to 1–2 choices per enemy for clean AI branching
#   • HP / Armor values scaled down ~30% from wiki for shorter encounters
# ─────────────────────────────────────────────────────────────────────────────

ENEMIES: dict[str, dict] = {

    # ── GRINEER LANCER ────────────────────────────────────────────────────────
    # Wiki: Grineer Lancer — basic Grakata-wielding frontline trooper.
    # TB Role: Aggressive ranged attacker; no shields, moderate armor.
    # ─────────────────────────────────────────────────────────────────────────
    "grineer_lancer": {
        "name":     "Grineer Lancer",
        "faction":  "Grineer",
        "hp":       150,
        "shields":  0,
        "armor":    100,    # wiki: 100 base armor
        "behavior": "aggressive",
        "icon":     E.grineer_lancer,
        "xp_reward": 40,
        "abilities": [
            {
                "name":        "Grakata Burst",
                "damage":      35,
                "damage_type": "impact",
                "effect":      None,
                "target":      "front",
                "chance":      1.0,
                "description": "Unleashes a tight burst from his Grakata — reliable, consistent damage.",
            },
            {
                "name":        "Suppressive Fire",
                "damage":      22,
                "damage_type": "impact",
                "effect":      "knockdown",
                "target":      "front",
                "chance":      0.35,  # 35% chance to Knockdown
                "description": "Sustained raking fire that can stagger and knock the target to the ground.",
            },
        ],
    },

    # ── GRINEER BUTCHER ───────────────────────────────────────────────────────
    # Wiki: Grineer Butcher — melee Cleaver-wielding brute.
    # TB Role: Aggressive melee; high HP, guaranteed Bleed on Cleave.
    # ─────────────────────────────────────────────────────────────────────────
    "grineer_butcher": {
        "name":     "Grineer Butcher",
        "faction":  "Grineer",
        "hp":       220,
        "shields":  0,
        "armor":    65,     # wiki: 65 base armor
        "behavior": "aggressive",
        "icon":     E.grineer_butcher,
        "xp_reward": 55,
        "abilities": [
            {
                "name":        "Cleave",
                "damage":      55,
                "damage_type": "slash",
                "effect":      "slash_bleed",
                "target":      "front",
                "chance":      1.0,   # always Bleeds — wiki: Slash-heavy weapon
                "bleed_mag":   18,    # 18 true damage/turn for 2 turns
                "description": "A brutal horizontal chop with his Cleaver — guaranteed Slash proc.",
            },
            {
                "name":        "Overhead Smash",
                "damage":      75,
                "damage_type": "impact",
                "effect":      "knockdown",
                "target":      "front",
                "chance":      0.55,
                "description": "A two-handed overhead blow. Heavy damage; good chance of Knockdown.",
            },
        ],
    },

    # ── GRINEER SCORPION (REPLACING CORPUS CREWMAN) ────────────────────────────
    # Wiki: Grineer Scorpion — Shotgun-wielding unit with grappling hook pull.
    # TB Role: Close-range / Disruptor; moderate armor, reposition control unit.
    # ───────────────────────────────────────────────────────────────────────────
    "grineer_scorpion": {
        "name": "Grineer Scorpion ",
        "faction": "Grineer",
        "hp": 150,
        "shields": 0,
        "armor": 200,
        "behavior": "melee",
        "icon": E.grineer_scorpion,
        "xp_reward": 60,
        "abilities": [
            {
                "name": "Shotgun Blast",
                "damage": 45,
                "damage_type": "impact",
                "effect": None,
                "target": "front",
                "chance": 1.0,
                "description": "Close-range shotgun attack — high Impact damage.",
            },
            {
                "name": "Grapple Hook",
                "damage": 20,
                "damage_type": "slash",
                "effect": "pull",
                "target": "front",
                "chance": 0.6,
                "description": "Launches a hook that pulls the target in and deals Slash damage.",
            },
        ],
    },
}

# ── Intro encounter pool ──────────────────────────────────────────────────────
# Exactly 3 enemies for the starter mission (one of each faction type).
INTRO_ENCOUNTER: list[str] = [
    "grineer_lancer",
    "grineer_butcher",
    "grineer_scorpion",
]
