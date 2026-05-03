# utils/weapon_embeds.py
# ─────────────────────────────────────────────────────────────────────────────
# Weapon-selection embed builders for all three loadout slots.
#
# Public API:
#   build_weapon_entry_embed()              → Primary entry    (step 2 of 4)
#   build_secondary_entry_embed()           → Secondary entry  (step 3 of 4)
#   build_melee_entry_embed()               → Melee entry      (step 4 of 4)
#   build_weapon_embed(key, player, ...)    → Detail card for any weapon
#
# All entry embeds use Lotus dialogue lifted from the Awakening quest.
# build_weapon_embed() is slot-aware via profile_key.
# ─────────────────────────────────────────────────────────────────────────────

import discord
from data.weapons import (
    WEAPONS,
    PRIMARY_CHOICES, SECONDARY_CHOICES, MELEE_CHOICES,
)
from utils.polarity_embeds import add_polarity_field_to_weapon_embed

_STEP_LABELS = {
    "primary":   ("Step 2 of 4", "Primary Weapon"),
    "secondary": ("Step 3 of 4", "Secondary Weapon"),
    "melee":     ("Step 4 of 4", "Melee Weapon"),
}


# ── Internal shared builder ───────────────────────────────────────────────────

def _build_slot_entry_embed(
    slot:        str,
    choices:     list[str],
    lotus_quote: str,
    lotus_tip:   str,
    author_line: str,
) -> discord.Embed:
    """Generic entry embed for any weapon slot. Weapon list built from WEAPONS data."""
    step_tag, step_label = _STEP_LABELS.get(slot, ("Step ? of 4", slot.capitalize()))

    lines = []
    for key in choices:
        wp = WEAPONS[key]
        lines.append(
            f"{wp['emoji']} **{wp['name']}** — *{wp['role']}*\n"
            f"⠀{wp['play_style'].split('.')[0].strip()}."
        )
    weapon_listing = "\n\n".join(lines)

    embed = discord.Embed(
        title=f"✦  Choose Your {step_label}, Tenno  ✦",
        description=(
            f"{lotus_quote}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{weapon_listing}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{lotus_tip}\n\n"
            "Browse your options below and press **✅ Choose** when ready.\n"
            "Your selection will be saved to your Tenno profile."
        ),
        color=0x1F4E5F,
    )
    embed.set_author(name=author_line)
    embed.set_footer(
        text=f"{step_tag}  ·  Use the menu below to preview  ·  Warframe © Digital Extremes"
    )
    return embed


# ── Entry embeds — one per slot ───────────────────────────────────────────────

def build_weapon_entry_embed() -> discord.Embed:
    """Primary weapon entry — Step 2 of 4."""
    return _build_slot_entry_embed(
        slot="primary",
        choices=PRIMARY_CHOICES,
        lotus_quote=(
            "*\"Good. Your Warframe is awake.\n"
            "Now — your Primary weapon. This is what you carry into the field.\n"
            "The Grineer are between us and extraction. Choose carefully, Operator.\"*"
        ),
        lotus_tip=(
            "> *\"Will you hold the line with sustained fire,\n"
            "> or strike once — and strike true?\"*"
        ),
        author_line="The Lotus  |  \"Every Tenno has a weapon that fits their hand.\"",
    )


def build_secondary_entry_embed() -> discord.Embed:
    """Secondary weapon entry — Step 3 of 4."""
    return _build_slot_entry_embed(
        slot="secondary",
        choices=SECONDARY_CHOICES,
        lotus_quote=(
            "*\"Your primary weapon is secured.\n"
            "But the Grineer fight in numbers, Operator — one weapon is never enough.\n"
            "Your sidearm is what you reach for when everything else has failed.\"*"
        ),
        lotus_tip=(
            "> *\"Reliability, or precision?\n"
            "> Both have brought Tenno home.\"*"
        ),
        author_line="The Lotus  |  \"I have seen Tenno fall for lack of a backup plan.\"",
    )


def build_melee_entry_embed() -> discord.Embed:
    """Melee weapon entry — Step 4 of 4."""
    return _build_slot_entry_embed(
        slot="melee",
        choices=MELEE_CHOICES,
        lotus_quote=(
            "*\"Almost ready, Operator. One final choice.\n"
            "The Grineer do not stay at range — they will close the distance.\n"
            "When your guns fall silent and they are in front of you,\n"
            "this is all that stands between you and them.\"*"
        ),
        lotus_tip=(
            "> *\"Choose your melee weapon.\n"
            "> Then we deploy — there is no more time.\"*\n\n"
            "⚔️ After this, your loadout is complete. Combat begins immediately."
        ),
        author_line="The Lotus  |  \"This is your last preparation before the field, Operator.\"",
    )


# ── Weapon detail embed ───────────────────────────────────────────────────────

def build_weapon_embed(
    key:         str,
    player:      dict | None = None,
    confirmed:   bool = False,
    profile_key: str  = "weapon",
) -> discord.Embed:
    """
    Full detail card for a single weapon.
    Slot-aware via profile_key: "weapon" | "secondary_weapon" | "melee_weapon"
    """
    wp = WEAPONS[key]

    embed = discord.Embed(
        description=f"*{wp['lore']}*",
        color=wp["color"],
    )
    embed.set_author(name=f"{wp['name']}  ·  {wp['type']}")

    if wp.get("thumbnail_url"):
        embed.set_thumbnail(url=wp["thumbnail_url"])

    # ── Play style ────────────────────────────────────────────────────────────
    embed.add_field(name="PLAY STYLE", value=wp["play_style"], inline=False)

    # ── Damage breakdown ──────────────────────────────────────────────────────
    d = wp["damage"]
    embed.add_field(
        name="DAMAGE",
        value=(
            f"<:impact:1499636596633374780> Impact      **{d['impact']}**\n"
            f"<:puncture:1499594734421803060> Puncture    **{d['puncture']}**\n"
            f"<:slash_effect:1499584690859020459> Slash       **{d['slash']}**\n"
            f"<:damage:1499651176419950622> **Total       {d['total']}** / action"
        ),
        inline=True,
    )

    # ── Key stats ─────────────────────────────────────────────────────────────
    embed.add_field(
        name="STATS",
        value="\n".join(f"**{k}** · {v}" for k, v in wp["stats"].items()),
        inline=True,
    )

    # ── Special perks ─────────────────────────────────────────────────────────
    if wp["perks"]:
        embed.add_field(
            name="SPECIAL PROPERTIES",
            value="\n".join(f"• {p}" for p in wp["perks"]),
            inline=False,
        )

    # ── Strengths / Weaknesses ────────────────────────────────────────────────
    embed.add_field(
        name="STRENGTHS",
        value="\n".join(
            f"<:stat_positive:1499636780356337715> {s}" for s in wp["strengths"]
        ),
        inline=True,
    )
    embed.add_field(
        name="WEAKNESSES",
        value="\n".join(
            f"<:stat_negative:1499636840494399638> {w}" for w in wp["weaknesses"]
        ),
        inline=True,
    )

    # ── Polarity mod slots ────────────────────────────────────────────────────
    add_polarity_field_to_weapon_embed(embed, wp["name"])

    # ── Footer — state-dependent ──────────────────────────────────────────────
    current_weapon = player.get(profile_key) if player else None

    if confirmed and current_weapon == wp["name"]:
        footer_text = (
            f"✅  {wp['name']} selected  ·  Loadout saved  ·  "
            f"Moving to the next step, Tenno."
        )
    elif current_weapon == wp["name"]:
        footer_text = (
            f"👁  Previewing  ·  This is already your active "
            f"{wp['slot'].capitalize()} weapon"
        )
    else:
        footer_text = (
            f"👁  Previewing {wp['name']}  ·  "
            f"Press ✅ Choose to equip, or 🔙 Back to browse"
        )

    embed.set_footer(text=footer_text)
    return embed
