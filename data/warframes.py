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
#   • "Sprint Speed" removed — identical across all frames, irrelevant in TB.
#   • Energy costs follow a 25 / 50 / 75 / 100 ladder for consistent balance.
#
# Emoji reference (assets.txt):
#   Energy        <a:energy_orb:1499636329842212964>   ← animated, note <a:
#   Health        <a:health:1499636458309423215>         ← animated, note <a:
#   Shield        <:wf_shield:1499636531755745280>
#   Armor / DR    <:damage_reduction:1499651603945226260>
#   Damage        <:damage:1499651176419950622>
#   Slash proc    <:slash_effect:1499584690859020459>
#   Puncture      <:puncture:1499594734421803060>
#   Impact        <:impact:1499636596633374780>
#   Magnetic      <:magnetic:1499594471770427472>
#   Blast         <:blast:1499594820102914210>
#   Electricity   <:electricity:1499596184958795917>
#   Stunned/KD    <:stunned:1499671616479563826>
#   Combo         <:combo:1499663262520971326>
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
        "play_style": "<:damage:1499588167655882815> Damage",
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
        "emoji": "<:excalibur_icon:1499569316138586244>",
        "stats": {
            "<a:health:1499636458309423215> Health":              "270  →  370 (Rank 30)",
            "<:wf_shield:1499636531755745280> Shields":           "270  →  370 (Rank 30)",
            "<:damage_reduction:1499651603945226260> Armor":      "240",
            "<a:energy_orb:1499636329842212964> Energy":          "100  →  150 (Rank 30)",
        },
        # Wiki: "Excalibur deals 10% increased damage and attacks 10% faster
        # when wielding swords."  Two separate flat bonuses, always active.
        # TB: "attack priority" replaces "attack speed" — he acts before enemies.
        "passive": (
            "+10% <:damage:1499651176419950622> damage and +10% attack priority "
            "*(acts before enemies)* when wielding a sword."
        ),
        "abilities": [
            (
                "<:slash_dash:1499574774429515917> **Slash Dash** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Strike through all enemies in a line — Excalibur is **untargetable this turn**. "
                "The strike auto-chains to additional nearby enemies; each one hit inflicts a guaranteed "
                "<:slash_effect:1499584690859020459> **Slash proc** *(Bleed: deals bonus damage for 2 turns)* "
                "and <:stunned:1499671616479563826> **Knockdown** *(target skips their next turn)*. "
                "Each successful hit adds **+1 <:combo:1499663262520971326> Combo Gauge stack** "
                "*(stacks increase melee damage)*. "
                "**Synergy:** While Exalted Blade is active, every hit also fires a "
                "piercing energy wave through all remaining enemies in the line.",
            ),
            (
                "<:radial_blind:1499574926364119050> **Radial Blind** "
                "(50 <a:energy_orb:1499636329842212964>)",
                "Raise the Exalted Blade and release an intense flash of light, "
                "**Blinding all enemies for 2 turns** *(Blinded enemies skip their attacks and "
                "are open to melee **Finisher** strikes dealing an **800% damage bonus**)*. "
                "**Synergy:** While Exalted Blade is active, each melee combo strike emits a "
                "secondary flash that refreshes the Blind on nearby enemies for 1 turn.",
            ),
            (
                "<:radial_javelin:1499575401343877391> **Radial Javelin** "
                "(75 <a:energy_orb:1499636329842212964>)",
                "Slam the Exalted Blade into the ground, hurling ethereal javelins at "
                "**every enemy simultaneously** (no target cap). "
                "Damage is split "
                "70% <:slash_effect:1499584690859020459> Slash / "
                "15% <:puncture:1499594734421803060> Puncture / "
                "15% <:impact:1499636596633374780> Impact. "
                "Each javelin inflicts a guaranteed "
                "<:slash_effect:1499584690859020459> **Slash proc** *(Bleed: 2 turns)*. "
                "Survivors are <:stunned:1499671616479563826> **stunned for 1 turn**.",
            ),
            (
                "<:exalted_blade:1499575259526074468> **Exalted Blade** "
                "(25 <a:energy_orb:1499636329842212964> + 1.25/turn)",
                "Draw an ethereal Skana, replacing your melee weapon for the duration "
                "*(deactivate any turn to stop the energy drain)*. "
                "Damage is split "
                "70% <:slash_effect:1499584690859020459> Slash / "
                "15% <:puncture:1499594734421803060> Puncture / "
                "15% <:impact:1499636596633374780> Impact. "
                "Every melee attack simultaneously fires a **piercing energy wave** through all "
                "enemies behind the primary target, dealing equal base damage to each. "
                "Each melee combo strike can emit a secondary flash that **Blinds nearby enemies for 1 turn**. "
                "Slash Dash gains bonus damage while this is active.",
            ),
        ],
        "weapons": [
            "<:braton:1499699815813218325> MK1-Braton",
            "<:lato:1499699965109207051> Lato",
            "<:skana:1499700067672526899> Skana",
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
        "play_style": "<:crowd_control:1499605208865439744> Crowd Control",
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
        "emoji": "<:mag_icon:1499569028916842536>",
        "stats": {
            "<a:health:1499636458309423215> Health":              "75   →  225 (Rank 30)",
            "<:wf_shield:1499636531755745280> Shields":           "150  →  450 (Rank 30)",
            "<:damage_reduction:1499651603945226260> Armor":      "105",
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
                "<:pull:1499595083547410643> **Pull** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Unleash a magnetic vortex that pulls **all enemies** toward Mag, "
                "dealing <:magnetic:1499594471770427472> Magnetic damage and inflicting "
                "<:stunned:1499671616479563826> **Knockdown** *(targets skip their next turn)*. "
                "Forces airborne enemies to the ground, removing their evasion bonus. "
                "Still deals full damage to crowd-control-immune targets.",
            ),
            (
                "<:magnetize:1499595149091668103> **Magnetize** "
                "(50 <a:energy_orb:1499636329842212964>)",
                "**CAST** — Enclose a single target in a magnetic field for **3 turns**: "
                "the target is **anchored** *(cannot act or escape)*, all ranged attacks — "
                "from allies and enemies alike — are automatically redirected into it, "
                "and all damage it receives is **doubled**. "
                "When the field expires or the target dies, it **explodes** for "
                "<:blast:1499594820102914210> Blast damage to all adjacent enemies.\n"
                "**HOLD CAST** — Mag forms a defensive singularity around herself instead, "
                "**absorbing all incoming ranged attacks for 1 turn**, then releases "
                "all stored damage as a targeted burst on her next action.\n"
                "**Synergy:** Crush deals massive bonus <:magnetic:1499594471770427472> Magnetic damage "
                "to the Magnetized target. Polarize Shards drawn into the bubble "
                "greatly amplify the explosion.",
            ),
            (
                "<:polarize:1499595238786994246> **Polarize** "
                "(75 <a:energy_orb:1499636329842212964>)",
                "Emit a magnetic pulse that sweeps across **all enemies**, "
                "**stripping their shields and armor** and dealing "
                "<:magnetic:1499594471770427472> Magnetic damage equal to what was stripped. "
                "Simultaneously **restores <:wf_shield:1499636531755745280> shields** for Mag and all allies. "
                "Stripped material scatters as **Polarize Shards** that orbit Mag — "
                "each turn, Shards cut nearby enemies for "
                "<:puncture:1499594734421803060> Puncture and "
                "<:slash_effect:1499584690859020459> Slash status procs.\n"
                "**Synergy:** Pull draws Shards to Mag instantly. "
                "Magnetize absorbs Shards into the bubble, greatly amplifying its explosion.",
            ),
            (
                "<:crush:1499595185888428234> **Crush** "
                "(100 <a:energy_orb:1499636329842212964>)",
                "Magnetize the bones of **all enemies**, suspending them and crushing them in "
                "**3 successive waves** of <:magnetic:1499594471770427472> Magnetic damage over the turn. "
                "The final wave triggers "
                "<:stunned:1499671616479563826> **Knockdown** *(targets skip their next turn)*. "
                "Each wave **restores a portion of <:wf_shield:1499636531755745280> shields** "
                "for Mag and all allies.\n"
                "**Synergy:** Each wave deals a massive extra hit of "
                "<:magnetic:1499594471770427472> Magnetic damage to any enemy currently under Magnetize.",
            ),
        ],
        "weapons": [
            "<:braton:1499699815813218325> MK1-Braton",
            "<:lato:1499699965109207051> Lato",
            "<:skana:1499700067672526899> Skana",
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
        "play_style": "<:damage:1499588167655882815> Damage",
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
        "emoji": "<:volt_icon:1499569244386627694>",
        "stats": {
            "<a:health:1499636458309423215> Health":              "100  →  300 (Rank 30)",
            "<:wf_shield:1499636531755745280> Shields":           "150  →  450 (Rank 30)",
            "<:damage_reduction:1499651603945226260> Armor":      "105",
            "<a:energy_orb:1499636329842212964> Energy":          "100  →  150 (Rank 30)",
        },
        # Wiki: "Grounded movement generates an electrical charge (up to 1,000
        # bonus damage per meter) that is unleashed with Volt's next attack."
        # TB: each turn Volt skips using an ability he stores 1 charge (max 5),
        # released automatically on his next attack as bonus Electricity damage.
        "passive": (
            "Each turn Volt does not cast an ability, he builds 1 **Static Discharge** charge *(max 5)*. "
            "His next attack automatically releases all stored charges as bonus "
            "<:electricity:1499596184958795917> Electricity damage."
        ),
        "abilities": [
            (
                "<:shock:1499596261375086732> **Shock** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Launch a voltaic arc that **chains between up to 3 enemies**, "
                "dealing <:electricity:1499596184958795917> Electricity damage and "
                "<:stunned:1499671616479563826> **stunning the initial target for 1 turn**.\n"
                "**Synergy:** Casting Shock on an enemy under Discharge's effect triggers an "
                "**Overcharge Burst** — a pulse that damages all enemies adjacent to the target. "
                "Casting Shock through an active Electric Shield **electrifies** the barrier, "
                "causing it to deal <:electricity:1499596184958795917> Electricity damage "
                "to any enemy that attacks through it.",
            ),
            (
                "<:speed:1499596301984071832> **Speed** "
                "(25 <a:energy_orb:1499636329842212964>)",
                "Surge with electrical energy, granting Volt and all allies "
                "**+50% <:damage:1499651176419950622> damage on all actions** and a "
                "**bonus action this round** for **2 turns**. "
                "Also reduces all active ability cooldowns by **1 turn**. "
                "Allies may forfeit the bonus action if unwanted.",
            ),
            (
                "<:electric_shield:1499596339674349658> **Electric Shield** "
                "(50 <a:energy_orb:1499636329842212964>)",
                "Erect an energy barrier that **blocks all incoming ranged attacks for 3 turns**. "
                "All ranged attacks fired through the shield by Volt and allies gain "
                "**+50% <:electricity:1499596184958795917> Electricity damage** and **2× critical damage**. "
                "Multiple shields stack their Electricity bonus additively.\n"
                "**Synergy:** Casting Shock through the shield electrifies it — "
                "enemies that attack through the shield take "
                "<:electricity:1499596184958795917> Electricity damage in return.",
            ),
            (
                "<:discharge:1499596381508075550> **Discharge** "
                "(100 <a:energy_orb:1499636329842212964>)",
                "Release a powerful electric pulse that hits **all enemies**. "
                "Every enemy struck is <:stunned:1499671616479563826> **stunned for 2 turns** "
                "and becomes a **Tesla Coil** — "
                "at the start of each stunned turn, the coil automatically arcs "
                "<:electricity:1499596184958795917> Electricity damage to all other enemies adjacent to it. "
                "Ignores cover; does not require line of sight.\n"
                "**Synergy:** Casting Shock on any Tesla Coil enemy triggers an "
                "**Overcharge Burst**, dealing a bonus pulse of damage to all adjacent foes.",
            ),
        ],
        "weapons": [
            "<:braton:1499699815813218325> MK1-Braton",
            "<:lato:1499699965109207051> Lato",
            "<:skana:1499700067672526899> Skana",
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
