# utils/embeds.py
# ─────────────────────────────────────────────────────────────────────────────
# Warframe codex embed builders.
# Dialogue sourced from the Awakening quest — voice of the Lotus.
# ─────────────────────────────────────────────────────────────────────────────

import discord
from data.warframes import WARFRAMES
from utils.polarity_embeds import add_polarity_fields_to_warframe_embed


# ── Entry embed ───────────────────────────────────────────────────────────────

def build_entry_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✦  The Tenno Awakens  ✦",
        description=(
            "*\"You've been sleeping for a very long time, Operator.\n"
            "I'm sorry to wake you this way — but they've found you.\n"
            "The Grineer are here. We must move quickly.\"*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "*\"There are Warframes here — left behind from another time.\n"
            "Each one remembers war. Each one is waiting.\n"
            "I need you to choose one. It will fight for you.\n"
            "It will protect you. But first — you must wake it.\"*\n\n"
            "> *Choose your Warframe. Then choose your weapons.\n"
            "> The Grineer will not wait.*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Browse the Warframes below and press **✅ Choose** when ready.\n"
            "Your Warframe, your weapons, your mission — chosen in sequence."
        ),
        color=0x1F4E5F,
    )
    embed.set_author(name="The Lotus  |  \"I will not abandon you, Operator.\"")
    embed.set_footer(text="Warframe selection  ·  Step 1 of 4  ·  Warframe © Digital Extremes")
    return embed


# ── Warframe detail embed ─────────────────────────────────────────────────────

def build_warframe_embed(
    key:       str,
    player:    dict | None = None,
    confirmed: bool = False,
) -> discord.Embed:
    wf = WARFRAMES[key]

    embed = discord.Embed(
        description=f"*{wf['lore']}*",
        color=wf["color"],
    )

    embed.set_author(name=wf["name"], icon_url=wf["icon_url"])
    embed.set_thumbnail(url=wf["thumbnail_url"])

    embed.add_field(
        name="PLAY STYLE",
        value=wf["play_style"],
        inline=False,
    )

    stats_lines = "\n".join(
        f"**{k}** · {v}" for k, v in wf["stats"].items()
    )
    embed.add_field(name="BASE STATS", value=stats_lines, inline=True)
    embed.add_field(name="PASSIVE",    value=wf["passive"], inline=True)

    for i, (name, desc) in enumerate(wf["abilities"]):
        embed.add_field(
            name="ABILITIES" if i == 0 else "\u200b",
            value=f"{name}\n{desc}",
            inline=False,
        )

    # STARTING WEAPONS field intentionally omitted —
    # players choose their weapons in the subsequent loadout steps.

    # ── Polarity slot grid ────────────────────────────────────────────────────
    add_polarity_fields_to_warframe_embed(embed, key, player)

    # Footer — state-dependent
    if confirmed and player and player.get("warframe") == wf["name"]:
        footer_text = (
            f"✅  {wf['name']} confirmed  ·  "
            f"Next: choose your Primary weapon, Operator."
        )
    elif player and player.get("warframe") == wf["name"]:
        footer_text = "👁  Previewing  ·  This is already your active Warframe"
    else:
        footer_text = (
            f"👁  Previewing {wf['name']}  ·  "
            f"Press ✅ Choose to confirm, or 🔙 Back to browse"
        )

    embed.set_footer(text=footer_text)
    return embed
