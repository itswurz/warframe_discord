from utils.emojis import E
# data/warframes.py
# ─────────────────────────────────────────────────────────────────────────────
# Canonical Warframe codex data — adapted for turn-based combat.
# Each entry is consumed by the embed-builder in cogs/warframe.py.
#
# Turn-based conventions used throughout:
#   • All real-world distances (meters) removed — abilities hit "all enemies,"
#     "one target," "adjacent enemies," etc.
#   • All real-time speeds (m/s) removed.
#   • "Slide / aerial / wall attacks" → "melee combo strike" or removed.
#   • TAP / HOLD controller labels → CAST / HOLD CAST.
#   • Stun durations are always explicit ("1 turn," "2 turns" — never "briefly").
#   • "Sprint Speedf" removed — identical across all frames, irrelevant in TB.
#   • Energy costs follow a 25 / 50 / 75 / 100 ladder for consistent balance.
#
# Emoji reference (assets.txt):
#   Energy        <a:energy_orb:1499636329842212964>   ← animated, note <a:
#   Health        <a:health:1499636458309423215>         ← animated, note <a:
#   Shield        {E.shield}
#   Armor / DR    {E.defense}
#   Damage        {E.location}
#   Slash proc    {E.slash}
#   Puncture      {E.puncture}
#   Impact        {E.impact}
#   Magnetic      {E.magnetic}
#   Blast         {E.blast}
#   Electricity   {E.electricity}
#   Stunned/KD    {E.stunned}
#   Combo         {E.combo}
# ─────────────────────────────────────────────────────────────────────────────

WARFRAMES = {
    # ── EXCALIBUR ─────────────────────────────────────────────────────────────
    # Wiki: https://wiki.warframe.com/w/Excalibur
    # Playstyle: Damage  |  Progenitor Element: Electricity
    # Role in TB: Melee DPS / Blind CC — bursts single targets, chains to
    #             nearby enemies, and locks down the whole field cheaply to
    #             punish with high-multiplier Finisher strikes.
    # ─────────────────────────────────────────────────────────────────────────
    "excalibur": {
        "name": "Excalibur",
        "role": "Damage",
        "play_style": f"{E.damage('damage')} Damage",
        "color": 0x1F4E5F,
        "icon_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499564757223735376/20251109191243ExcaliburLargePortrait.png"
            "?ex=69f54202&is=69f3f082&hm=b96e546cb7ac49e1f9ebc653724c87476247e36ba9089a67522f9e8f1eecebf1&"
        ),
        "thumbnail_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499564757223735376/20251109191243ExcaliburLargePortrait.png"
            "?ex=69f54202&is=69f3f082&hm=b96e546cb7ac49e1f9ebc653724c87476247e36ba9089a67522f9e8f1eecebf1&"
        ),
        "emoji": E.excalibur,
        "stats": {
            "<a:health:1499636458309423215> Health":              "270  →  370 (Rank 30)",
            f"{E.shield} Shields":           "270  →  370 (Rank 30)",
            f"{E.defense} Armor":      "240",
            "<a:energy_orb:1499636329842212964> Energy":          "100  →  150 (Rank 30)",
        },
        # Wiki: "Excalibur deals 10% increased damage and attacks 10% faster
        # when wielding swords."  Two separate flat bonuses, always active.
        # TB: "attack priority" replaces "attack speed" — he acts before enemies.
        "passive": (
            f"+10% {E.location} damage and +10% attack priority "
            "*(acts before enemies)* when wielding a sword."
        ),
        "abilities": [
            (
                f"{E.slash_dash} **Slash Dash** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Strike through all enemies in a line — Excalibur is **untargetable this turn**. "
                "The strike auto-chains to additional nearby enemies; each one hit inflicts a guaranteed "
                f"{E.slash} **Slash proc** *(Bleed: deals bonus damage for 2 turns)* "
                f"and {E.stunned} **Knockdown** *(target skips their next turn)*. "
                f"Each successful hit adds **+1 {E.combo} Combo Gauge stack** "
                "*(stacks increase melee damage)*. "
                "**Synergy:** While Exalted Blade is active, every hit also fires a "
                "piercing energy wave through all remaining enemies in the line.",
            ),
            (
                f"{E.radial_blind} **Radial Blind** "
                "(50 <a:energy_orb:1499636329842212964>)",
                "Raise the Exalted Blade and release an intense flash of light, "
                "**Blinding all enemies for 2 turns** *(Blinded enemies skip their attacks and "
                "are open to melee **Finisher** strikes dealing an **800% damage bonus**)*. "
                "**Synergy:** While Exalted Blade is active, each melee combo strike emits a "
                "secondary flash that refreshes the Blind on nearby enemies for 1 turn.",
            ),
            (
                f"{E.radial_javelin} **Radial Javelin** "
                "(75 <a:energy_orb:1499636329842212964>)",
                "Slam the Exalted Blade into the ground, hurling ethereal javelins at "
                "**every enemy simultaneously** (no target cap). "
                "Damage is split "
                f"70% {E.slash} Slash / "
                f"15% {E.puncture} Puncture / "
                f"15% {E.impact} Impact. "
                "Each javelin inflicts a guaranteed "
                f"{E.slash} **Slash proc** *(Bleed: 2 turns)*. "
                f"Survivors are {E.stunned} **stunned for 1 turn**.",
            ),
            (
                f"{E.exalted_blade} **Exalted Blade** "
                "(25 <a:energy_orb:1499636329842212964> + 1.25/turn)",
                "Draw an ethereal Skana, replacing your melee weapon for the duration "
                "*(deactivate any turn to stop the energy drain)*. "
                "Damage is split "
                f"70% {E.slash} Slash / "
                f"15% {E.puncture} Puncture / "
                f"15% {E.impact} Impact. "
                "Every melee attack simultaneously fires a **piercing energy wave** through all "
                "enemies behind the primary target, dealing equal base damage to each. "
                "Each melee combo strike can emit a secondary flash that **Blinds nearby enemies for 1 turn**. "
                "Slash Dash gains bonus damage while this is active.",
            ),
        ],
        "weapons": [
            f"{E.braton} MK1-Braton",
            f"{E.lato} Lato",
            f"{E.skana} Skana",
        ],
        "lore": (
            "A master of gun and blade, Excalibur is the embodiment of martial excellence. "
            "The first Warframe chosen by many Tenno, his affinity with swords transcends both blade and Void."
        ),
    },

    # ── MAG ───────────────────────────────────────────────────────────────────
    # Wiki: https://wiki.warframe.com/w/Mag
    # Playstyle: Crowd Control  |  Progenitor Element: Magnetic
    # Role in TB: CC Debuffer / Shield Engine — locks down key targets with
    #             Magnetize, strips enemy defenses with Polarize, and keeps
    #             the whole team's shields healthy through Polarize + Crush.
    # ─────────────────────────────────────────────────────────────────────────
    "mag": {
        "name": "Mag",
        "role": "Crowd Control",
        "play_style": f"{E.crowd_control} Crowd Control",
        "color": 0x1F4E5F,
        "icon_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499564580790075392/20251109191240MagLargePortrait.png"
            "?ex=69f541d8&is=69f3f058&hm=082176f21478bb7fcd2e8085c49338e4e358425a80d7958ea9f3227f8ae65060&"
        ),
        "thumbnail_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499564580790075392/20251109191240MagLargePortrait.png"
            "?ex=69f541d8&is=69f3f058&hm=082176f21478bb7fcd2e8085c49338e4e358425a80d7958ea9f3227f8ae65060&"
        ),
        "emoji": E.mag,
        "stats": {
            "<a:health:1499636458309423215> Health":              "75   →  225 (Rank 30)",
            f"{E.shield} Shields":           "150  →  450 (Rank 30)",
            f"{E.defense} Armor":      "105",
            "<a:energy_orb:1499636329842212964> Energy":          "125  →  188 (Rank 30)",
        },
        # Wiki: "Nearby items gravitate towards Mag for easy collection."
        # TB: at the start of each of Mag's turns, all uncollected Energy Orbs
        # and Health Orbs on the field are automatically picked up.
        "passive": (
            "At the start of each turn, all "
            "<a:energy_orb:1499636329842212964> Energy Orbs and "
            "<a:health:1499636458309423215> Health Orbs on the field are automatically collected."
        ),
        "abilities": [
            (
                f"{E.pull} **Pull** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Unleash a magnetic vortex that pulls **all enemies** toward Mag, "
                f"dealing {E.magnetic} Magnetic damage and inflicting "
                f"{E.stunned} **Knockdown** *(targets skip their next turn)*. "
                "Forces airborne enemies to the ground, removing their evasion bonus. "
                "Still deals full damage to crowd-control-immune targets.",
            ),
            (
                f"{E.magnetize} **Magnetize** "
                "(50 <a:energy_orb:1499636329842212964>)",
                "**CAST** — Enclose a single target in a magnetic field for **3 turns**: "
                "the target is **anchored** *(cannot act or escape)*, all ranged attacks — "
                "from allies and enemies alike — are automatically redirected into it, "
                "and all damage it receives is **doubled**. "
                "When the field expires or the target dies, it **explodes** for "
                f"{E.blast} Blast damage to all adjacent enemies.\n"
                "**HOLD CAST** — Mag forms a defensive singularity around herself instead, "
                "**absorbing all incoming ranged attacks for 1 turn**, then releases "
                "all stored damage as a targeted burst on her next action.\n"
                f"**Synergy:** Crush deals massive bonus {E.magnetic} Magnetic damage "
                "to the Magnetized target. Polarize Shards drawn into the bubble "
                "greatly amplify the explosion.",
            ),
            (
                f"{E.polarize} **Polarize** "
                "(75 <a:energy_orb:1499636329842212964>)",
                "Emit a magnetic pulse that sweeps across **all enemies**, "
                "**stripping their shields and armor** and dealing "
                f"{E.magnetic} Magnetic damage equal to what was stripped. "
                f"Simultaneously **restores {E.shield} shields** for Mag and all allies. "
                "Stripped material scatters as **Polarize Shards** that orbit Mag — "
                "each turn, Shards cut nearby enemies for "
                f"{E.puncture} Puncture and "
                f"{E.slash} Slash status procs.\n"
                "**Synergy:** Pull draws Shards to Mag instantly. "
                "Magnetize absorbs Shards into the bubble, greatly amplifying its explosion.",
            ),
            (
                f"{E.crush} **Crush** "
                "(100 <a:energy_orb:1499636329842212964>)",
                "Magnetize the bones of **all enemies**, suspending them and crushing them in "
                f"**3 successive waves** of {E.magnetic} Magnetic damage over the turn. "
                "The final wave triggers "
                f"{E.stunned} **Knockdown** *(targets skip their next turn)*. "
                f"Each wave **restores a portion of {E.shield} shields** "
                "for Mag and all allies.\n"
                "**Synergy:** Each wave deals a massive extra hit of "
                f"{E.magnetic} Magnetic damage to any enemy currently under Magnetize.",
            ),
        ],
        "weapons": [
            f"{E.braton} MK1-Braton",
            f"{E.lato} Lato",
            f"{E.skana} Skana",
        ],
        "lore": (
            "Take down your enemies with magnetic force. Mag alters electromagnetic fields to provide "
            "crowd control and strip enemy defenses. Few can resist her attraction — or her repulsion."
        ),
    },

    # ── VOLT ──────────────────────────────────────────────────────────────────
    # Wiki: https://wiki.warframe.com/w/Volt
    # Playstyle: Damage  |  Progenitor Element: Electricity
    # Role in TB: Electric DPS / Speed Support — chains damage across the whole
    #             field cheaply, buffs the entire team's actions, and builds
    #             devastating synergies between Shock, Electric Shield, and
    #             Discharge.
    # ─────────────────────────────────────────────────────────────────────────
    "volt": {
        "name": "Volt",
        "role": "Damage",
        "play_style": f"{E.damage('damage')} Damage",
        "color": 0x1F4E5F,
        "icon_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499564130267304056/20230627042846VoltLargePortrait.png"
            "?ex=69f5416d&is=69f3efed&hm=fafd20ade9585acfeef2204d1c6790ed70a40810ca2836e17205e2fba58d19fb&"
        ),
        "thumbnail_url": (
            "https://cdn.discordapp.com/attachments/1499564077075267617"
            "/1499564130267304056/20230627042846VoltLargePortrait.png"
            "?ex=69f5416d&is=69f3efed&hm=fafd20ade9585acfeef2204d1c6790ed70a40810ca2836e17205e2fba58d19fb&"
        ),
        "emoji": E.volt,
        "stats": {
            "<a:health:1499636458309423215> Health":              "100  →  300 (Rank 30)",
            f"{E.shield} Shields":           "150  →  450 (Rank 30)",
            f"{E.defense} Armor":      "105",
            "<a:energy_orb:1499636329842212964> Energy":          "100  →  150 (Rank 30)",
        },
        # Wiki: "Grounded movement generates an electrical charge (up to 1,000
        # bonus damage per meter) that is unleashed with Volt's next attack."
        # TB: each turn Volt skips using an ability he stores 1 charge (max 5),
        # released automatically on his next attack as bonus Electricity damage.
        "passive": (
            "Each turn Volt does not cast an ability, he builds 1 **Static Discharge** charge *(max 5)*. "
            "His next attack automatically releases all stored charges as bonus "
            f"{E.electricity} Electricity damage."
        ),
        "abilities": [
            (
                f"{E.shock} **Shock** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Launch a voltaic arc that **chains between up to 3 enemies**, "
                f"dealing {E.electricity} Electricity damage and "
                f"{E.stunned} **stunning the initial target for 1 turn**.\n"
                "**Synergy:** Casting Shock on an enemy under Discharge's effect triggers an "
                "**Overcharge Burst** — a pulse that damages all enemies adjacent to the target. "
                "Casting Shock through an active Electric Shield **electrifies** the barrier, "
                f"causing it to deal {E.electricity} Electricity damage "
                "to any enemy that attacks through it.",
            ),
            (
                f"{E.speed} **Speed** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Surge with electrical energy, granting Volt and all allies "
                f"**+50% {E.location} damage on all actions** and a "
                "**bonus action this round** for **2 turns**. "
                "Also reduces all active ability cooldowns by **1 turn**. "
                "Allies may forfeit the bonus action if unwanted.",
            ),
            (
                f"{E.electric_shield} **Electric Shield** "
                "(50 <a:energy_orb:1499636329842212964>)",
                "Erect an energy barrier that **blocks all incoming ranged attacks for 3 turns**. "
                "All ranged attacks fired through the shield by Volt and allies gain "
                f"**+50% {E.electricity} Electricity damage** and **2× critical damage**. "
                "Multiple shields stack their Electricity bonus additively.\n"
                "**Synergy:** Casting Shock through the shield electrifies it — "
                "enemies that attack through the shield take "
                f"{E.electricity} Electricity damage in return.",
            ),
            (
                f"{E.discharge} **Discharge** "
                "(100 <a:energy_orb:1499636329842212964>)",
                "Release a powerful electric pulse that hits **all enemies**. "
                f"Every enemy struck is {E.stunned} **stunned for 2 turns** "
                "and becomes a **Tesla Coil** — "
                "at the start of each stunned turn, the coil automatically arcs "
                f"{E.electricity} Electricity damage to all other enemies adjacent to it. "
                "Ignores cover; does not require line of sight.\n"
                "**Synergy:** Casting Shock on any Tesla Coil enemy triggers an "
                "**Overcharge Burst**, dealing a bonus pulse of damage to all adjacent foes.",
            ),
        ],
        "weapons": [
            f"{E.braton} MK1-Braton",
            f"{E.lato} Lato",
            f"{E.skana} Skana",
        ],
        "lore": (
            "One of the original Warframes engineered by the Orokin, Volt wields raw electricity "
            "to accelerate allies and electrocute entire squads of enemies. "
            "Electricity flows through Volt — his attacks deal high damage, and enemies will be shocked."
        ),
    },
}

# ── Select-menu option list (order matters) ───────────────────────────────────
SELECT_OPTIONS = [
    discord_option
    for key in ("excalibur", "mag", "volt")
    for discord_option in [(
        WARFRAMES[key]["emoji"],
        key,
        WARFRAMES[key]["name"],
        WARFRAMES[key]["play_style"].split("/")[0].strip(),
    )]
]
