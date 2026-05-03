# data/weapons.py
# ─────────────────────────────────────────────────────────────────────────────
# Full player-choice weapon codex for all three loadout slots.
#
#   PRIMARY   — MK1-Braton · Paris
#   SECONDARY — Lato · Kunai
#   MELEE     — Skana · Bo
#
# Wiki sources (unmodded, Rank 0):
#   MK1-Braton : https://wiki.warframe.com/w/MK1-Braton
#   Paris      : https://wiki.warframe.com/w/Paris
#   Lato       : https://wiki.warframe.com/w/Lato
#   Kunai      : https://wiki.warframe.com/w/Kunai
#   Skana      : https://wiki.warframe.com/w/Skana
#   Bo         : https://wiki.warframe.com/w/Bo
#
# Turn-based conventions:
#   • Fire rate / attack speed → "hits per action" notation.
#   • Magazine / reload not tracked until ammo system is added.
#   • Crit + status rolled per hit. Punch-Through hits all enemies in line.
#   • Slash DoT bypasses armor & shields. Impact procs Knockdown (1 turn).
#   • Melee (Skana/Bo) damage is scaled from wiki base; see TB notes per weapon.
# ─────────────────────────────────────────────────────────────────────────────

WEAPONS: dict[str, dict] = {

    # ──────────────────────────────────────────────────────────────────────────
    # PRIMARY WEAPONS
    # ──────────────────────────────────────────────────────────────────────────

    # ── MK1-BRATON ────────────────────────────────────────────────────────────
    "braton": {
        "name":          "MK1-Braton",
        "slot":          "primary",
        "type":          "Primary — Assault Rifle",
        "trigger":       "Auto",
        "role":          "Balanced Damage",
        "emoji":         "<:braton:1499699815813218325>",
        "color":         0x1F4E5F,
        "thumbnail_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499705236208615474/Braton.png"
            "?ex=69f5c4d7&is=69f47357"
            "&hm=85255d8524ccb058cf69e67c349cfa2e86ced5abceb225d1f15472c94a854e04&"
        ),
        "lore": (
            "The standard-issue Tenno assault rifle, reforged as the MK1 variant for new Operators. "
            "Reliable, adaptable, and forgiving — the Braton rewards those who learn its rhythm."
        ),
        "play_style": (
            "A full-auto rifle that sprays three rapid bursts per action, splitting damage across "
            "<:impact:1499636596633374780> Impact · "
            "<:puncture:1499594734421803060> Puncture · "
            "<:slash_effect:1499584690859020459> Slash almost equally. "
            "Consistent sustained pressure — effective against any target type, specialist against none."
        ),
        "damage": {
            "impact":   round(7.92 * 3, 1),
            "puncture": round(7.92 * 3, 1),
            "slash":    round(8.16 * 3, 1),
            "total":    72,
        },
        "stats": {
            "Damage / Action": "72  *(3 hits × 24 base)*",
            "Crit Chance":     "12%  per hit",
            "Crit Multiplier": "1.6×",
            "Status Chance":   "6%  per hit",
            "Hits / Action":   "3  rapid bursts",
            "Noise":           "🔊 Alarming",
        },
        "perks": [],
        "strengths": [
            "Even IPS split — can proc any physical status",
            "Three hits per action raises practical crit/proc frequency",
            "No charge time — immediate, fires every action",
            "Effective against all enemy types regardless of faction",
        ],
        "weaknesses": [
            "Lower single-hit damage than the Paris",
            "Moderate crit ceiling — struggles against very high armor",
            "Status chance per hit is low; procs are not guaranteed",
            "🔊 Alarming — alerts nearby enemies",
        ],
    },

    # ── PARIS ─────────────────────────────────────────────────────────────────
    "paris": {
        "name":          "Paris",
        "slot":          "primary",
        "type":          "Primary — Bow",
        "trigger":       "Charge",
        "role":          "High-Crit Precision",
        "emoji":         "<:paris:1499699912445661214>",
        "color":         0x1F4E5F,
        "thumbnail_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499705236506542161/Paris.png"
            "?ex=69f5c4d7&is=69f47357"
            "&hm=bb87e50790753878f7a88a1609aa154cdadf9b9f49e79a30b65180cfb9f74432&"
        ),
        "lore": (
            "A precision compound bow favored by Tenno who strike from the shadows. "
            "Silent. Lethal. The Paris demands patience — and rewards it with devastating crits."
        ),
        "play_style": (
            "A charged bow that fires one devastating arrow per action, dealing overwhelming "
            "<:puncture:1499594734421803060> Puncture damage. "
            "Each arrow **Punch-Throughs** the primary target and pierces every enemy in the line. "
            "30% crit chance with a 2.0× multiplier makes critical strikes common. "
            "Fires silently — nearby enemies are never alerted."
        ),
        "damage": {
            "impact":   16,
            "puncture": 256,
            "slash":    48,
            "total":    320,
        },
        "stats": {
            "Damage / Action": "320  *(1 arrow — 80% Puncture)*",
            "Crit Chance":     "**30%**  per arrow",
            "Crit Multiplier": "**2.0×**",
            "Status Chance":   "10%  per arrow",
            "Hits / Action":   "1  charged arrow  *(pierces all in line)*",
            "Noise":           "🔇 **Silent** — never alerts enemies",
        },
        "perks": [
            (
                "<:puncture:1499594734421803060> **Punch-Through** — "
                "Each arrow passes through the primary target and strikes every enemy "
                "behind them in the same line for full damage."
            ),
            (
                "🔇 **Silent** — "
                "The bowstring makes no noise. Nearby Grineer are never alerted."
            ),
        ],
        "strengths": [
            "Highest burst damage of any starter weapon (320 per action)",
            "30% crit chance — reliable crits nearly every fight",
            "Punch-Through pierces and damages every enemy in the line",
            "Silent — never triggers enemy reinforcements",
        ],
        "weaknesses": [
            "One arrow per action — low sustained DPS if target survives",
            "Low Impact component — weak against shielded enemies",
            "Missing an action is a significant setback",
        ],
    },

    # ──────────────────────────────────────────────────────────────────────────
    # SECONDARY WEAPONS
    # ──────────────────────────────────────────────────────────────────────────

    # ── LATO ──────────────────────────────────────────────────────────────────
    # Wiki: Impact 10, Puncture 10, Slash 20 = 40 total.  Fire rate 6.67.
    # TB: 1 shot per action; slight Slash lean (50 %).
    "lato": {
        "name":          "Lato",
        "slot":          "secondary",
        "type":          "Secondary — Semi-Auto Pistol",
        "trigger":       "Semi-Auto",
        "role":          "Balanced Sidearm",
        "emoji":         "<:lato:1499699965109207051>",
        "color":         0x1F4E5F,
        "thumbnail_url": None,   # add CDN URL when asset is available
        "lore": (
            "The standard Tenno sidearm, reissued to every new Operator. "
            "The Lato is unremarkable in almost every way — and that, paradoxically, "
            "is precisely what makes it trustworthy."
        ),
        "play_style": (
            "A semi-auto pistol that fires one accurate shot per action, splitting damage with a "
            "<:slash_effect:1499584690859020459> Slash lean (50 %). "
            "Balanced stats mean it is equally serviceable against shields, armor, and raw HP. "
            "The Tenno's reliable backup when the Primary runs dry."
        ),
        "damage": {
            "impact":   10,
            "puncture": 10,
            "slash":    20,
            "total":    40,
        },
        "stats": {
            "Damage / Action": "40  *(1 shot — 50% Slash)*",
            "Crit Chance":     "10%  per shot",
            "Crit Multiplier": "1.5×",
            "Status Chance":   "10%  per shot",
            "Hits / Action":   "1  accurate shot",
            "Noise":           "🔊 Alarming",
        },
        "perks": [],
        "strengths": [
            "Balanced IPS — effective against any target type",
            "10% crit chance — modest but reliable occasional boosts",
            "Immediate fire, no charge or wind-up",
            "Familiar, predictable performance in any situation",
        ],
        "weaknesses": [
            "Lowest raw damage per action of the four secondary options",
            "Alarming — may alert nearby enemies",
            "No unique mechanics; purely a reliable workhorse",
        ],
    },

    # ── KUNAI ─────────────────────────────────────────────────────────────────
    # Wiki: Impact 7.5, Puncture 22.5, Slash 15 = 45 total.
    #       Fire rate 3.33.  Silent.  Status Chance 15 %.  Crit 5 % / 1.5×.
    # TB: 1 throw per action.  50 % Puncture — weakens enemy attack output.
    "kunai": {
        "name":          "Kunai",
        "slot":          "secondary",
        "type":          "Secondary — Thrown",
        "trigger":       "Semi-Auto",
        "role":          "Silent Disabler",
        "emoji":         "<:kunai:1499920860344094830>",
        "color":         0x1F4E5F,
        "thumbnail_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499919849747517613/Kunai.png"
            "?ex=69f68cb7&is=69f53b37"
            "&hm=624d1987e2ac6b90fbf9f3b19c4c142854c1bf370f516ccffb313d9973a042ad&"
        ),
        "lore": (
            "An ancient throwing blade reforged in Orokin alloy. "
            "No muzzle flash, no report — only the brief whisper of steel through air, "
            "and then silence. The Grineer never hear it coming."
        ),
        "play_style": (
            "A thrown sidearm that hurls one precision kunai per action, dealing heavy "
            "<:puncture:1499594734421803060> Puncture damage (50 %). "
            "**Puncture procs reduce enemy damage output by 30 %** for 1 turn — critical against "
            "high-damage Butchers and Scorpions. "
            "Fires silently; 15 % status chance beats the Lato's. "
            "The specialist's choice for debuffing and stealth."
        ),
        "damage": {
            "impact":   8,
            "puncture": 22,
            "slash":    15,
            "total":    45,
        },
        "stats": {
            "Damage / Action": "45  *(1 throw — 50% Puncture)*",
            "Crit Chance":     "5%  per throw",
            "Crit Multiplier": "1.5×",
            "Status Chance":   "**15%**  per throw",
            "Hits / Action":   "1  precision throw",
            "Noise":           "🔇 **Silent** — never alerts enemies",
        },
        "perks": [
            (
                "<:puncture:1499594734421803060> **Puncture Proc** — "
                "A Puncture status reduces the target's damage output by **-30 %** for 1 turn, "
                "softening their next attack on you."
            ),
            (
                "🔇 **Silent** — "
                "Thrown blades produce no sound. "
                "Nearby Grineer are never alerted when the Kunai is used."
            ),
        ],
        "strengths": [
            "15% status chance — highest of any secondary; reliable procs",
            "Puncture procs debuff enemy damage output (-30 % for 1 turn)",
            "Silent — never triggers enemy reinforcements",
            "50% Puncture deals bonus damage vs armored targets",
        ],
        "weaknesses": [
            "5% crit — the lowest of any weapon; crits are rare",
            "1 throw per action — lower raw DPS than burst-fire options",
            "Weak Impact component; poor against shielded enemies",
        ],
    },

    # ──────────────────────────────────────────────────────────────────────────
    # MELEE WEAPONS
    # ──────────────────────────────────────────────────────────────────────────

    # ── SKANA ─────────────────────────────────────────────────────────────────
    # Wiki: Impact 18, Puncture 18, Slash 84 = 120 total.  AS 0.83.
    #       Crit 5 % / 1.5×.  Status 16 %.
    # TB: 1 swing per action; 70 % Slash → bypasses armor entirely.
    "skana": {
        "name":          "Skana",
        "slot":          "melee",
        "type":          "Melee — Sword",
        "trigger":       "N/A",
        "role":          "Armor-Cutting Damage",
        "emoji":         "<:skana:1499700067672526899>",
        "color":         0x1F4E5F,
        "thumbnail_url": None,   # add CDN URL when asset is available
        "lore": (
            "The Skana has been the Tenno's blade since before the Old War ended. "
            "It does not ask questions. It does not hesitate. "
            "It cuts, and in doing so, it ends things."
        ),
        "play_style": (
            "A single-handed sword that delivers one powerful slash per action. "
            "**70 % Slash damage bypasses armor entirely in TB** — the Skana hits HP directly, "
            "making it devastating against the heavily armored Grineer Scorpion. "
            "High base damage (120) and 16 % status give it strong Bleed proc potential. "
            "The Excalibur passive grants +10 % bonus damage when this weapon is equipped."
        ),
        "damage": {
            "impact":   18,
            "puncture": 18,
            "slash":    84,
            "total":    120,
        },
        "stats": {
            "Damage / Action": "120  *(1 swing — 70% Slash)*",
            "Crit Chance":     "5%  per swing",
            "Crit Multiplier": "1.5×",
            "Status Chance":   "**16%**  per swing",
            "Hits / Action":   "1  sword swing",
            "Special":         "<:excalibur_icon:1499569316138586244> +10% dmg with Excalibur",
        },
        "perks": [
            (
                "<:slash_effect:1499584690859020459> **Armor-Piercing Slash** — "
                "Slash damage bypasses enemy armor in turn-based combat, dealing full damage "
                "directly to HP. Extremely effective against Grineer."
            ),
            (
                "<:excalibur_icon:1499569316138586244> **Excalibur Passive** — "
                "Excalibur deals +10 % damage when wielding a sword. "
                "Also enables the full Exalted Blade synergy."
            ),
        ],
        "strengths": [
            "Slash bypasses armor — full damage vs every Grineer unit",
            "Highest base damage of either melee choice (120)",
            "16% status chance — reliable Bleed procs each combat",
            "Excalibur passive bonus; required for Exalted Blade synergy",
        ],
        "weaknesses": [
            "5% crit — critical strikes are uncommon",
            "Impact proc (18 dmg) and Puncture proc (18 dmg) are diluted by Slash",
            "No CC utility beyond Bleed DoT",
        ],
    },

    # ── BO ────────────────────────────────────────────────────────────────────
    # Wiki: Impact 42, Puncture 8.4, Slash 9.6 = 60 total. AS 1.0. Status 10%.
    # TB: scaled to 100 total (Impact dominant), 70% Impact → Knockdown proc.
    #     Impact damage is reduced by armor but the Knockdown proc cancels
    #     an enemy's next turn — a powerful stall on high-damage enemies.
    "bo": {
        "name":          "Bo",
        "slot":          "melee",
        "type":          "Melee — Staff",
        "trigger":       "N/A",
        "role":          "Crowd-Control Disabler",
        "emoji":         "<:bo_staff:1499920804866031797>",
        "color":         0x1F4E5F,
        "thumbnail_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499919849508573346/Bo.png"
            "?ex=69f68cb7&is=69f53b37"
            "&hm=4769aaf45ba4a3c02a339fc1726a529e375031bd2cfb6e5afa1687aff019e86b&"
        ),
        "lore": (
            "A long metal staff forged under Orokin specifications. "
            "The Bo does not cut. It does not pierce. "
            "It breaks — bones, formations, resolve. "
            "A single strike can end a charge before it begins."
        ),
        "play_style": (
            "A reach weapon that delivers one sweeping strike per action, dealing heavy "
            "<:impact:1499636596633374780> Impact damage (70 %). "
            "**Impact procs cause Knockdown — the target skips their next turn.** "
            "10 % status chance means roughly 1-in-10 swings disables an attacker entirely. "
            "Armor reduces Impact damage, so the Bo shines against unarmored or lightly armored targets. "
            "The Tenno's choice when controlling the fight matters more than raw lethality."
        ),
        "damage": {
            "impact":   70,
            "puncture": 14,
            "slash":    16,
            "total":    100,
        },
        "stats": {
            "Damage / Action": "100  *(1 swing — 70% Impact, armor-reduced)*",
            "Crit Chance":     "5%  per swing",
            "Crit Multiplier": "1.5×",
            "Status Chance":   "10%  per swing",
            "Hits / Action":   "1  staff sweep",
            "Special":         "<:stunned:1499671616479563826> Knockdown on Impact proc",
        },
        "perks": [
            (
                "<:stunned:1499671616479563826> **Impact Knockdown** — "
                "An Impact status proc (10 % chance per swing) causes **Knockdown**, "
                "forcing the target to skip their next turn entirely."
            ),
        ],
        "strengths": [
            "Impact Knockdown can neutralize a dangerous enemy for a full turn",
            "Lower armor class than Grineer means Impact penalty is manageable",
            "100 TB damage before reduction — competitive base number",
            "Useful against any faction; Knockdown works on all enemy types",
        ],
        "weaknesses": [
            "Impact is reduced by enemy armor (25 % reduction vs Lancer at 100 armor)",
            "Lower effective damage than Skana vs heavily armored Grineer",
            "10% status — Knockdown not guaranteed each swing",
            "No Excalibur passive bonus (Bo is not a sword)",
        ],
    },
}

# ── Choice pools per slot ─────────────────────────────────────────────────────
PRIMARY_CHOICES:   list[str] = ["braton",  "paris"]
SECONDARY_CHOICES: list[str] = ["lato",    "kunai"]
MELEE_CHOICES:     list[str] = ["skana",   "bo"]

# Profile key that stores the player's choice for each slot
SLOT_PROFILE_KEY: dict[str, str] = {
    "primary":   "weapon",
    "secondary": "secondary_weapon",
    "melee":     "melee_weapon",
}

# Default weapon name if no choice has been saved yet
SLOT_DEFAULTS: dict[str, str] = {
    "primary":   "MK1-Braton",
    "secondary": "Lato",
    "melee":     "Skana",
}
