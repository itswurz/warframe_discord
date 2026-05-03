import discord
from discord.ext import commands
import os
import asyncio

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


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
        await bot.start(TOKEN)


@bot.event
async def on_ready():
    print(f"[Ordis] Online as {bot.user} (ID: {bot.user.id})")
    print(f"[Ordis] Serving {len(bot.guilds)} guild(s).")


if __name__ == "__main__":
    asyncio.run(main())
