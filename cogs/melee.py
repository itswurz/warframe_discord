# cogs/melee.py
# ─────────────────────────────────────────────────────────────────────────────
# Melee weapon selection — Step 4 of the loadout flow.
#
# Flow:
#   SecondaryView (secondary.py) → MeleeView (here) → CombatSession (combat.py)
#
# ChooseMeleeButton saves the Melee choice to the profile, then launches
# the CombatSession using all three saved weapon choices.
#
# Change from original:
#   After session creation, calls mark_player_initialized() so that
#   subsequent !warframe invocations show the Orbiter instead of the tutorial.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from discord.ext import commands

from data.weapons import WEAPONS, MELEE_CHOICES, SLOT_DEFAULTS
from data import persistence
from utils.emojis import E
from utils.weapon_embeds import (
    build_melee_entry_embed,
    build_weapon_embed,
)


# ─────────────────────────────────────────────────────────────────────────────
# Buttons
# ─────────────────────────────────────────────────────────────────────────────

class ChooseMeleeButton(discord.ui.Button):
    """Saves the chosen Melee weapon and launches the CombatSession."""

    def __init__(self, weapon_key: str):
        self.weapon_key = weapon_key
        wp_name = WEAPONS[weapon_key]["name"]
        super().__init__(
            style=discord.ButtonStyle.success,
            label=f"Choose {wp_name}",
            emoji="✅",
            custom_id=f"choose_melee_{weapon_key}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            # ── 1. Persist the melee weapon choice ────────────────────────────
            profile     = await persistence.load_player(interaction.user.id)
            weapon_name = WEAPONS[self.weapon_key]["name"]
            profile["melee_weapon"] = weapon_name
            await persistence.save_player(profile)

            # ── 2. Resolve saved Warframe ─────────────────────────────────────
            from data.warframes import WARFRAMES
            wf_name = profile.get("warframe")
            if not wf_name:
                await interaction.response.send_message(
                    "🔒 No Warframe on record. Use `!warframe` first, Tenno.",
                    ephemeral=True,
                )
                return

            wf_key = next(
                (k for k, v in WARFRAMES.items() if v["name"] == wf_name), None
            )
            if wf_key is None:
                await interaction.response.send_message(
                    f"❌ Warframe `{wf_name}` not found. Use `!warframe` to re-select.",
                    ephemeral=True,
                )
                return

            # ── 3. Guard — clear any finished session, block active ones ──────
            from combat.session import CombatSession, ACTIVE_SESSIONS
            existing = ACTIVE_SESSIONS.get(interaction.user.id)
            if existing and not existing.is_over:
                await interaction.response.send_message(
                    "⚔️ You are already in combat, Tenno! "
                    "Finish your current mission or use `!abort` first.",
                    ephemeral=True,
                )
                return
            ACTIVE_SESSIONS.pop(interaction.user.id, None)

            # ── 4. Resolve all three weapon names from profile ────────────────
            from combat.weapons import WEAPON_STATS

            primary_name   = profile.get("weapon")           or SLOT_DEFAULTS["primary"]
            secondary_name = profile.get("secondary_weapon") or SLOT_DEFAULTS["secondary"]
            melee_name     = weapon_name   # just saved above

            # Validate each against the combat registry, fall back to defaults
            if primary_name not in WEAPON_STATS:
                primary_name = SLOT_DEFAULTS["primary"]
            if secondary_name not in WEAPON_STATS:
                secondary_name = SLOT_DEFAULTS["secondary"]
            if melee_name not in WEAPON_STATS:
                melee_name = SLOT_DEFAULTS["melee"]

            # ── 5. Create and register the session ────────────────────────────
            session = CombatSession(
                warframe_key     = wf_key,
                warframe_data    = WARFRAMES[wf_key],
                user_id          = interaction.user.id,
                primary_weapon   = primary_name,
                secondary_weapon = secondary_name,
                melee_weapon     = melee_name,
                profile          = profile,
            )
            ACTIVE_SESSIONS[interaction.user.id] = session

            # ── 6. Mark the player as initialized (tutorial complete) ─────────
            # Deferred import to avoid circular dependency
            from cogs.warframe import mark_player_initialized
            await mark_player_initialized(interaction.user.id)

            # ── 7. Build and send the combat embed ────────────────────────────
            from utils.combat_embeds import build_combat_embed
            from cogs.combat import CombatView

            pw = WEAPON_STATS.get(primary_name,   {})
            sw = WEAPON_STATS.get(secondary_name, {})
            mw = WEAPON_STATS.get(melee_name,     {})

            embed = build_combat_embed(session, session.log[-10:])
            view  = CombatView(session)
            session._active_view = view

            await interaction.response.edit_message(
                content=(
                    f"{E.lotus} Loadout locked, Operator. Deploying now.\n"
                    f"{pw.get('emoji', '')} **{primary_name}**  ·  "
                    f"{sw.get('emoji', '')} **{secondary_name}**  ·  "
                    f"{mw.get('emoji', '')} **{melee_name}**"
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


class BackToSecondaryButton(discord.ui.Button):
    """Returns to the secondary weapon selector."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Back",
            emoji="🔙",
            custom_id="melee_back",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from cogs.secondary import SecondaryView
        from utils.weapon_embeds import build_secondary_entry_embed

        embed = build_secondary_entry_embed()
        view  = SecondaryView()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ─────────────────────────────────────────────────────────────────────────────
# Select menu
# ─────────────────────────────────────────────────────────────────────────────

class MeleeSelect(discord.ui.Select):
    """Drop-down listing all Melee choices."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=WEAPONS[key]["name"],
                value=key,
                description=WEAPONS[key]["role"],
                emoji=WEAPONS[key]["emoji"],
            )
            for key in MELEE_CHOICES
        ]
        super().__init__(
            custom_id="melee_select_menu",
            placeholder="Browse Melee Weapons, Tenno…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key    = self.values[0]
        player = await persistence.load_player(interaction.user.id)
        embed  = build_weapon_embed(key, player, confirmed=False, profile_key="melee_weapon")
        view   = MeleeView(preview_key=key)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


# ─────────────────────────────────────────────────────────────────────────────
# View
# ─────────────────────────────────────────────────────────────────────────────

class MeleeView(discord.ui.View):
    """
    Row 0 — MeleeSelect (always present)
    Row 1 — ✅ ChooseMeleeButton + 🔙 BackToSecondaryButton  (only when previewing)
    """

    def __init__(self, preview_key: str | None = None):
        super().__init__(timeout=None)
        self.add_item(MeleeSelect())
        if preview_key:
            self.add_item(ChooseMeleeButton(preview_key))
            self.add_item(BackToSecondaryButton())


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class MeleeCog(commands.Cog, name="Melee"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(MeleeView())
        for key in MELEE_CHOICES:
            self.bot.add_view(MeleeView(preview_key=key))

    @commands.command(name="melee", aliases=["blade", "staff"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def melee_cmd(self, ctx: commands.Context) -> None:
        """Browse and equip your Melee weapon."""
        embed = build_melee_entry_embed()
        view  = MeleeView()
        await ctx.send(embed=embed, view=view)

    @melee_cmd.error
    async def melee_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Ordis is recalibrating. "
                f"Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MeleeCog(bot))
