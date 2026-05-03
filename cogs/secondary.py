# cogs/secondary.py
# ─────────────────────────────────────────────────────────────────────────────
# Secondary weapon selection — Step 3 of the loadout flow.
#
# Flow:
#   WeaponView (weapon.py) → SecondaryView (here) → MeleeView (melee.py)
#
# ChooseSecondaryButton saves the Secondary choice to the profile, then
# hands off to the melee weapon selector. Combat is NOT launched here.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from discord.ext import commands

from data.weapons import WEAPONS, SECONDARY_CHOICES
from data import persistence
from utils.emojis import E
from utils.weapon_embeds import (
    build_secondary_entry_embed,
    build_weapon_embed,
    build_melee_entry_embed,
)


# ─────────────────────────────────────────────────────────────────────────────
# Buttons
# ─────────────────────────────────────────────────────────────────────────────

class ChooseSecondaryButton(discord.ui.Button):
    """Saves the chosen Secondary weapon and advances to the Melee selector."""

    def __init__(self, weapon_key: str):
        self.weapon_key = weapon_key
        wp_name = WEAPONS[weapon_key]["name"]
        super().__init__(
            style=discord.ButtonStyle.success,
            label=f"Choose {wp_name}",
            emoji="✅",
            custom_id=f"choose_secondary_{weapon_key}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            # ── 1. Persist the secondary weapon choice ────────────────────────
            profile     = await persistence.load_player(interaction.user.id)
            weapon_name = WEAPONS[self.weapon_key]["name"]
            profile["secondary_weapon"] = weapon_name
            if not profile.get("initialized", False):
                profile["tutorial_step"] = "melee_select"
            await persistence.save_player(profile)

            # ── 2. Transition to melee weapon selector ────────────────────────
            from cogs.melee import MeleeView

            embed = build_melee_entry_embed()
            view  = MeleeView()

            await interaction.response.edit_message(
                content=(
                    f"{E.lotus} "
                    f"{WEAPONS[self.weapon_key]['emoji']} **{weapon_name}** holstered, Operator.\n"
                    f"One final choice — your **Melee weapon**."
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


class BackToWeaponButton(discord.ui.Button):
    """Returns to the primary weapon entry overview."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Back",
            emoji="🔙",
            custom_id="secondary_back",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from cogs.weapon import WeaponView
        from utils.weapon_embeds import build_weapon_entry_embed

        embed = build_weapon_entry_embed()
        view  = WeaponView()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ─────────────────────────────────────────────────────────────────────────────
# Select menu
# ─────────────────────────────────────────────────────────────────────────────

class SecondarySelect(discord.ui.Select):
    """Drop-down listing all Secondary choices."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=WEAPONS[key]["name"],
                value=key,
                description=WEAPONS[key]["role"],
                emoji=WEAPONS[key]["emoji"],
            )
            for key in SECONDARY_CHOICES
        ]
        super().__init__(
            custom_id="secondary_select_menu",
            placeholder="Browse Secondary Weapons, Tenno…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key    = self.values[0]
        player = await persistence.load_player(interaction.user.id)
        embed  = build_weapon_embed(key, player, confirmed=False, profile_key="secondary_weapon")
        view   = SecondaryView(preview_key=key)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ─────────────────────────────────────────────────────────────────────────────
# View
# ─────────────────────────────────────────────────────────────────────────────

class SecondaryView(discord.ui.View):
    """
    Row 0 — SecondarySelect (always present)
    Row 1 — ✅ ChooseSecondaryButton + 🔙 BackToWeaponButton  (only when previewing)
    """

    def __init__(self, preview_key: str | None = None):
        super().__init__(timeout=None)
        self.add_item(SecondarySelect())
        if preview_key:
            self.add_item(ChooseSecondaryButton(preview_key))
            self.add_item(BackToWeaponButton())


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class SecondaryCog(commands.Cog, name="Secondary"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(SecondaryView())
        for key in SECONDARY_CHOICES:
            self.bot.add_view(SecondaryView(preview_key=key))

    @commands.command(name="secondary", aliases=["sidearm", "pistol"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def secondary_cmd(self, ctx: commands.Context) -> None:
        """Browse and equip your Secondary weapon."""
        embed = build_secondary_entry_embed()
        view  = SecondaryView()
        await ctx.send(embed=embed, view=view)

    @secondary_cmd.error
    async def secondary_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Ordis is recalibrating. "
                f"Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SecondaryCog(bot))
