# cogs/weapon.py
# ─────────────────────────────────────────────────────────────────────────────
# Primary weapon selection — Step 2 of the loadout flow.
#
# Flow:
#   ChooseButton (warframe.py) → WeaponView (here) → SecondaryView (secondary.py)
#
# ChooseWeaponButton saves the Primary choice to the profile, then
# hands off to the secondary weapon selector. Combat is NOT launched here.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from discord.ext import commands

from data.weapons import WEAPONS, PRIMARY_CHOICES
from data import persistence
from utils.weapon_embeds import (
    build_weapon_entry_embed,
    build_weapon_embed,
    build_secondary_entry_embed,
)


# ─────────────────────────────────────────────────────────────────────────────
# Buttons
# ─────────────────────────────────────────────────────────────────────────────

class ChooseWeaponButton(discord.ui.Button):
    """Saves the chosen Primary weapon and advances to the Secondary selector."""

    def __init__(self, weapon_key: str):
        self.weapon_key = weapon_key
        wp_name = WEAPONS[weapon_key]["name"]
        super().__init__(
            style=discord.ButtonStyle.success,
            label=f"Choose {wp_name}",
            emoji="✅",
            custom_id=f"choose_weapon_{weapon_key}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            # ── 1. Persist the primary weapon choice ──────────────────────────
            profile     = await persistence.load_player(interaction.user.id)
            weapon_name = WEAPONS[self.weapon_key]["name"]
            profile["weapon"] = weapon_name
            await persistence.save_player(profile)

            # ── 2. Transition to secondary weapon selector ────────────────────
            from cogs.secondary import SecondaryView

            embed = build_secondary_entry_embed()
            view  = SecondaryView()

            await interaction.response.edit_message(
                content=(
                    f"<:wf_lotus:1499651243101126816> "
                    f"{WEAPONS[self.weapon_key]['emoji']} **{weapon_name}** secured, Operator.\n"
                    f"Now choose your **Secondary weapon**."
                ),
                embed=embed,
                view=view,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(
                f"❌ Error: `{e}`", ephemeral=True
            )


class BackToMenuButton(discord.ui.Button):
    """Returns to the primary weapon entry overview."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Back",
            emoji="🔙",
            custom_id="weapon_back",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = build_weapon_entry_embed()
        view  = WeaponView()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ─────────────────────────────────────────────────────────────────────────────
# Select menu
# ─────────────────────────────────────────────────────────────────────────────

class WeaponSelect(discord.ui.Select):
    """Drop-down listing all Primary choices."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=WEAPONS[key]["name"],
                value=key,
                description=WEAPONS[key]["role"],
                emoji=WEAPONS[key]["emoji"],
            )
            for key in PRIMARY_CHOICES
        ]
        super().__init__(
            custom_id="weapon_select_menu",
            placeholder="Browse Primary Weapons, Tenno…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key    = self.values[0]
        player = await persistence.load_player(interaction.user.id)
        embed  = build_weapon_embed(key, player, confirmed=False, profile_key="weapon")
        view   = WeaponView(preview_key=key)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ─────────────────────────────────────────────────────────────────────────────
# View
# ─────────────────────────────────────────────────────────────────────────────

class WeaponView(discord.ui.View):
    """
    Row 0 — WeaponSelect (always present)
    Row 1 — ✅ ChooseWeaponButton + 🔙 BackToMenuButton  (only when previewing)
    """

    def __init__(self, preview_key: str | None = None):
        super().__init__(timeout=None)
        self.add_item(WeaponSelect())
        if preview_key:
            self.add_item(ChooseWeaponButton(preview_key))
            self.add_item(BackToMenuButton())


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class WeaponCog(commands.Cog, name="Weapon"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(WeaponView())
        for key in PRIMARY_CHOICES:
            self.bot.add_view(WeaponView(preview_key=key))

    @commands.command(name="weapon", aliases=["loadout", "arsenal", "primary"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def weapon_cmd(self, ctx: commands.Context) -> None:
        """Browse and equip your Primary weapon from the Tenno armory."""
        embed = build_weapon_entry_embed()
        view  = WeaponView()
        await ctx.send(embed=embed, view=view)

    @weapon_cmd.error
    async def weapon_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Ordis is recalibrating the armory. "
                f"Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeaponCog(bot))
