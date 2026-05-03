# cogs/polarity.py
# ─────────────────────────────────────────────────────────────────────────────
# Polarity system commands.
#
# Commands:
#   !polarity [warframe]        — Show polarity slot overview for the player's
#                                 current (or specified) Warframe.
#   !polarity mod <name>        — Show a mod's polarity and cost preview for
#                                 every matching slot type.
#   !polarity weapon <name>     — Show a weapon's mod-slot polarity grid.
#   !polarity reload            — (Owner-only) Reload polarities.json from disk.
#
# Integration points with existing embeds:
#   • weapon_embeds.build_weapon_embed()    → polarity slot row injected
#   • inventory_embeds.build_mod_embed()    → mod polarity shown in MOD INFO
#   • embeds.build_warframe_embed()         → WARFRAME MOD SLOTS field injected
#
# All injection is done by the polarity_embeds helpers — no changes to the
# existing embed functions are required; callers just need to call the inject
# helpers after building the base embed.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from discord.ext import commands

from data import persistence
from data.polarity import (
    emoji as pol_emoji,
    display as pol_display,
    mod_polarity,
    warframe_slot_polarities,
    weapon_slot_polarities,
    adjusted_drain,
    polarity_tag,
    reload as polarity_reload,
    _data as polarity_data,
    ANY,
)
from utils.polarity_embeds import (
    build_polarity_overview_embed,
    build_mod_polarity_line,
    build_weapon_slots_line,
    add_polarity_fields_to_warframe_embed,
    add_polarity_field_to_weapon_embed,
    slot_row,
    mod_drain_preview,
    _LEGEND,
    _BASE_CAPACITY,
)
from data.warframes import WARFRAMES


# ── Max drain values from item_descriptions (for drain preview) ───────────────
# Key: mod name → max_drain.  Pulled lazily; falls back to 10.
_MOD_MAX_DRAIN: dict[str, int] = {
    "Vitality":            14,
    "Redirection":         14,
    "Steel Fiber":         14,
    "Flow":                 6,
    "Streamline":           6,
    "Heavy Impact":         6,
    "Master Thief":         9,
    "Diamond Skin":         6,
    "Lightning Rod":        9,
    "Serration":           14,
    "Ammo Drum":            5,
    "Fast Hands":           9,
    "Rifle Ammo Mutation":  9,
    "Rifle Aptitude":       9,
    "North Wind":           9,
    "Blunderbuss":          5,
    "Heated Charge":        9,
    "Perpetual Agony":      9,
    "Pressure Point":      14,
    "Fever Strike":         9,
    "Heavy Trauma":         9,
    "Rending Strike":       9,
    "Reflex Coil":          9,
    "Focus Energy":         9,
    "Iron Phoenix":         2,
    "Tranquil Cleave":      2,
    "Defiled Snapdragon":   6,
    "Stance Mod (Various)": 2,
}

_SLOT_TYPE_LABELS = {
    "warframe":  "Warframe slot",
    "primary":   "Primary slot",
    "secondary": "Secondary slot",
    "melee":     "Melee slot",
}

_POLARITY_NAMES = {
    "madurai", "naramon", "vazarin", "zenurik",
    "unairu", "penjaga", "koneksi", "umbra", "any",
}


class PolarityCog(commands.Cog, name="Polarity"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─────────────────────────────────────────────────────────────────────────
    # !polarity  (base command)
    # ─────────────────────────────────────────────────────────────────────────

    @commands.group(
        name="polarity",
        aliases=["pol", "slots"],
        invoke_without_command=True,
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def polarity_cmd(
        self,
        ctx: commands.Context,
        *,
        warframe_name: str | None = None,
    ) -> None:
        """
        Show polarity slot overview for your active Warframe (or a named one).

        Usage:
          !polarity               — your current Warframe
          !polarity Excalibur     — any Warframe by name
        """
        profile = await persistence.load_player(ctx.author.id)

        # Resolve warframe key
        if warframe_name:
            wf_key = next(
                (k for k, v in WARFRAMES.items()
                 if v["name"].lower() == warframe_name.lower()),
                None,
            )
            if wf_key is None:
                names = ", ".join(f"**{v['name']}**" for v in WARFRAMES.values())
                await ctx.send(
                    f"<:wf_lotus:1499651243101126816> Warframe `{warframe_name}` not found. "
                    f"Available: {names}.",
                    delete_after=10,
                )
                return
        else:
            wf_name = profile.get("warframe")
            if not wf_name:
                await ctx.send(
                    "<:wf_lotus:1499651243101126816> You haven't chosen a Warframe yet. "
                    "Use `!warframe` first, Tenno.",
                    delete_after=8,
                )
                return
            wf_key = next(
                (k for k, v in WARFRAMES.items() if v["name"] == wf_name), None
            )
            if wf_key is None:
                await ctx.send(
                    f"<:wf_lotus:1499651243101126816> Warframe `{wf_name}` not found in codex. "
                    "Use `!warframe` to re-select.",
                    delete_after=8,
                )
                return

        embed = build_polarity_overview_embed(
            warframe_key  = wf_key,
            warframe_name = WARFRAMES[wf_key]["name"],
            profile       = profile,
        )
        await ctx.send(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # !polarity mod <name>
    # ─────────────────────────────────────────────────────────────────────────

    @polarity_cmd.command(name="mod", aliases=["m"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def polarity_mod(self, ctx: commands.Context, *, mod_name: str) -> None:
        """
        Show a mod's polarity and its adjusted cost in matching / mismatching slots.

        Usage:  !polarity mod Serration
        """
        mp       = mod_polarity(mod_name.strip())
        base     = _MOD_MAX_DRAIN.get(mod_name.strip(), 10)
        mp_em    = pol_emoji(mp)

        # Build a table of cost vs every polarity type
        all_pols = ["madurai", "naramon", "vazarin", "zenurik", "unairu",
                    "penjaga", "koneksi", "umbra", "any"]
        table_lines = []
        for sp in all_pols:
            adj = adjusted_drain(base, sp, mp)
            tag = polarity_tag(sp, mp)
            if tag.startswith("✅"):
                indicator = "✅"
            elif tag.startswith("⚪"):
                indicator = "⚪"
            else:
                indicator = "❌"
            table_lines.append(
                f"{indicator} {pol_emoji(sp)} **{sp.capitalize()}** slot  →  "
                f"**{adj}** drain  *(base {base})*"
            )

        embed = discord.Embed(
            title=f"{mp_em}  {mod_name.strip()}  —  Polarity",
            description=(
                f"This mod's polarity: **{mp_em} {mp.capitalize()}**\n\n"
                f"{_LEGEND}"
            ),
            color=0x1F4E5F,
        )
        embed.add_field(
            name="DRAIN COST PER SLOT TYPE",
            value="\n".join(table_lines),
            inline=False,
        )
        embed.set_footer(
            text=f"Base drain (max rank): {base}  ·  Warframe © Digital Extremes"
        )
        await ctx.send(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # !polarity weapon <name>
    # ─────────────────────────────────────────────────────────────────────────

    @polarity_cmd.command(name="weapon", aliases=["w", "wpn"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def polarity_weapon(self, ctx: commands.Context, *, weapon_name: str) -> None:
        """
        Show a weapon's mod-slot polarity grid.

        Usage:  !polarity weapon MK1-Braton
        """
        from data.polarity import _data as pd
        wpn_db = pd().get("weapons", {})

        # Case-insensitive lookup
        matched_name = next(
            (k for k in wpn_db if k.lower() == weapon_name.strip().lower()),
            None,
        )
        if matched_name is None:
            names = ", ".join(f"**{k}**" for k in wpn_db)
            await ctx.send(
                f"<:wf_lotus:1499651243101126816> Weapon `{weapon_name}` not found. "
                f"Available: {names}.",
                delete_after=10,
            )
            return

        slots = weapon_slot_polarities(matched_name)
        embed = discord.Embed(
            title=f"<:wf_lotus:1499651243101126816>  {matched_name} — Mod Slots",
            description=(
                f"{slot_row(slots)}\n\n"
                f"**{len(slots)} mod slots** available for this weapon."
            ),
            color=0x1F4E5F,
        )

        # Show drain table for common mods
        mod_examples = _get_weapon_mod_examples(matched_name)
        if mod_examples:
            cost_lines = []
            for mod_nm in mod_examples:
                base = _MOD_MAX_DRAIN.get(mod_nm, 10)
                mp   = mod_polarity(mod_nm)
                # Use first slot as representative
                sp   = slots[0] if slots else ANY
                adj  = adjusted_drain(base, sp, mp)
                tag  = polarity_tag(sp, mp)
                cost_lines.append(
                    f"{pol_emoji(mp)} **{mod_nm}**  "
                    f"→  slot {pol_emoji(sp)}  {tag}  **{adj}/{base}**"
                )
            embed.add_field(
                name=f"EXAMPLE MODS  (vs. {pol_emoji(slots[0] if slots else ANY)} slot 1)",
                value="\n".join(cost_lines),
                inline=False,
            )

        embed.add_field(name="POLARITY RULES", value=_LEGEND, inline=False)
        embed.set_footer(text="Warframe © Digital Extremes")
        await ctx.send(embed=embed)

    # ─────────────────────────────────────────────────────────────────────────
    # !polarity reload  (owner only)
    # ─────────────────────────────────────────────────────────────────────────

    @polarity_cmd.command(name="reload", hidden=True)
    @commands.is_owner()
    async def polarity_reload(self, ctx: commands.Context) -> None:
        """Reload polarities.json without restarting the bot."""
        try:
            polarity_reload()
            await ctx.send(
                "<:wf_lotus:1499651243101126816> `polarities.json` reloaded successfully.",
                delete_after=8,
            )
        except Exception as exc:
            await ctx.send(
                f"<:wf_lotus:1499651243101126816> ❌ Reload failed: `{exc}`",
                delete_after=10,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Error handlers
    # ─────────────────────────────────────────────────────────────────────────

    @polarity_cmd.error
    async def polarity_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Ordis is cross-referencing the codex. "
                f"Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        else:
            raise error

    @polarity_mod.error
    async def polarity_mod_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "<:wf_lotus:1499651243101126816> Please provide a mod name. "
                "Example: `!polarity mod Serration`",
                delete_after=8,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Try again in `{error.retry_after:.1f}s`.",
                delete_after=5,
            )
        else:
            raise error

    @polarity_weapon.error
    async def polarity_weapon_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "<:wf_lotus:1499651243101126816> Please provide a weapon name. "
                "Example: `!polarity weapon MK1-Braton`",
                delete_after=8,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Try again in `{error.retry_after:.1f}s`.",
                delete_after=5,
            )
        else:
            raise error


# ── Helper: pick representative mods for a weapon ─────────────────────────────

def _get_weapon_mod_examples(weapon_name: str) -> list[str]:
    """Return a short list of mods that are relevant to a weapon's category."""
    wn = weapon_name.lower()
    if "braton" in wn or "paris" in wn:
        return ["Serration", "North Wind", "Rifle Aptitude"]
    if "lato" in wn:
        return ["Heated Charge", "Perpetual Agony"]
    if "kunai" in wn:
        return ["Heated Charge", "North Wind"]
    if "skana" in wn:
        return ["Pressure Point", "Fever Strike", "Iron Phoenix"]
    if "bo" in wn:
        return ["Pressure Point", "Heavy Trauma"]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PolarityCog(bot))
