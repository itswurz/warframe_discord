import discord
from discord.ext import commands
import os
import asyncio

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ── Global command guard ──────────────────────────────────────────────────────
# Uninitialized players (still in tutorial) may only use !warframe and its
# subcommands.  Every other command is blocked with a friendly redirect.

@bot.check
async def require_initialized(ctx: commands.Context) -> bool:
    if ctx.command is None:
        return True
    qualified = ctx.command.qualified_name
    if qualified.startswith("warframe") or qualified == "abort":
        return True
    from data import persistence
    profile = await persistence.load_player(ctx.author.id)
    if not profile.get("initialized", False):
        await ctx.send(
            f"<:wf_lotus:1499651243101126816> "
            f"*\"Complete your training first, Operator.\"*\n"
            "Use `!warframe` to begin the tutorial.",
            delete_after=12,
        )
        return False
    return True


@bot.event
async def on_command_error(ctx: commands.Context, error) -> None:
    if isinstance(error, commands.CheckFailure):
        return
    raise error


# ── Load Cogs ─────────────────────────────────────────────────────────────────
async def main():
    async with bot:
        await bot.load_extension("cogs.warframe")    # Step 1 — Warframe selector
        await bot.load_extension("cogs.weapon")      # Step 2 — Primary weapon
        await bot.load_extension("cogs.secondary")   # Step 3 — Secondary weapon
        await bot.load_extension("cogs.melee")       # Step 4 — Melee weapon → launches combat
        await bot.load_extension("cogs.combat")      # Combat loop
        await bot.load_extension("cogs.inventory")   # Inventory + item viewer
        await bot.load_extension("cogs.mods")        # Mod collection, upgrade, view
        await bot.load_extension("cogs.polarity")    # Polarity system
        await bot.load_extension("cogs.quests")      # Quest log + progression
        await bot.load_extension("cogs.foundry")     # Foundry crafting system
        await bot.start(TOKEN)


@bot.event
async def on_ready():
    print(f"[Ordis] Online as {bot.user} (ID: {bot.user.id})")
    print(f"[Ordis] Serving {len(bot.guilds)} guild(s).")


if __name__ == "__main__":
    asyncio.run(main())
