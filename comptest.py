"""
Discord.py Components V2 — Buttons inside containers
=====================================================
Requires: discord.py >= 2.6
Install :  pip install -U discord.py
"""

import discord
from discord.ext import commands
from typing import Self

# ─── Bot setup ───────────────────────────────────────────────────────────────

# After
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─── Builder helper (from your example) ──────────────────────────────────────

class ContainerBuilder:
    def __init__(self, **container_kwargs):
        self.items = []
        self.container_kwargs = container_kwargs

    def add_text(self, content: str, *, id: int | None = None) -> Self:
        self.items.append(discord.ui.TextDisplay(content, id=id))
        return self

    def add_separator(
        self,
        *,
        visible: bool = True,
        spacing: discord.SeparatorSpacing = discord.SeparatorSpacing.small,
        id: int | None = None,
    ) -> Self:
        self.items.append(discord.ui.Separator(visible=visible, spacing=spacing, id=id))
        return self

    def add_media(self, attachment_url: str, *, id: int | None = None) -> Self:
        if attachment_url:
            self.items.append(
                discord.ui.MediaGallery(discord.MediaGalleryItem(attachment_url), id=id)
            )
        return self

    def add_item(self, item) -> Self:
        self.items.append(item)
        return self

    def add_action_row(self, *components, id: int | None = None) -> Self:
        self.items.append(discord.ui.ActionRow(*components, id=id))
        return self

    def add_section(self, *content, accessory=None, id: int | None = None) -> Self:
        self.items.append(discord.ui.Section(*content, accessory=accessory, id=id))
        return self

    def build(self) -> discord.ui.Container:
        return discord.ui.Container(*self.items, **self.container_kwargs)


# ─── !card — simple card with three buttons ───────────────────────────────────

@bot.command(name="card")
async def card_command(ctx: commands.Context):
    hello_btn = discord.ui.Button(label="Say Hello", style=discord.ButtonStyle.primary, emoji="👋")
    ping_btn  = discord.ui.Button(label="Ping",      style=discord.ButtonStyle.secondary, emoji="🏓")
    danger_btn = discord.ui.Button(label="Danger",   style=discord.ButtonStyle.danger,    emoji="⚠️")

    async def hello_cb(interaction: discord.Interaction):
        await interaction.response.send_message("Hello there! 👋", ephemeral=True)

    async def ping_cb(interaction: discord.Interaction):
        latency = round(interaction.client.latency * 1000)
        await interaction.response.send_message(f"Pong! **{latency} ms**", ephemeral=True)

    async def danger_cb(interaction: discord.Interaction):
        await interaction.response.send_message("You clicked the red button! 😱", ephemeral=True)

    hello_btn.callback  = hello_cb
    ping_btn.callback   = ping_cb
    danger_btn.callback = danger_cb

    container = (
        ContainerBuilder(accent_colour=0x5865F2)
        .add_text("## 🎉 Welcome to Components V2!")
        .add_text("Buttons now live **inside** the container — no more floating below.\nClick a button to see a response.")
        .add_separator()
        .add_action_row(hello_btn, ping_btn, danger_btn)
        .build()
    )

    layout = discord.ui.LayoutView()
    layout.add_item(container)
    await ctx.send(view=layout)


# ─── !status — two stacked containers ────────────────────────────────────────

@bot.command(name="status")
async def status_command(ctx: commands.Context):
    # Green card
    refresh_btn = discord.ui.Button(label="Refresh", style=discord.ButtonStyle.success, emoji="🔄")

    async def refresh_cb(interaction: discord.Interaction):
        await interaction.response.send_message("Status refreshed! (demo data 😄)", ephemeral=True)

    refresh_btn.callback = refresh_cb

    status_card = (
        ContainerBuilder(accent_colour=0x57F287)
        .add_text("## ✅ Server Status")
        .add_text("**API:** 🟢 Operational\n**Database:** 🟢 Operational\n**CDN:** 🟡 Degraded Performance")
        .add_separator(visible=False)
        .add_action_row(refresh_btn)
        .build()
    )

    # Red card
    incident_btn = discord.ui.Button(label="View Incident", style=discord.ButtonStyle.danger, emoji="📋")
    link_btn     = discord.ui.Button(label="Status Page",   style=discord.ButtonStyle.link,   emoji="🌐", url="https://discordstatus.com")

    async def incident_cb(interaction: discord.Interaction):
        await interaction.response.send_message("Opening incident report… (demo only)", ephemeral=True)

    incident_btn.callback = incident_cb

    incident_card = (
        ContainerBuilder(accent_colour=0xED4245)
        .add_text("## 🚨 Active Incidents")
        .add_text("**Incident #1042** — CDN latency elevated in EU-West\n*Started 14 minutes ago*")
        .add_separator(visible=False)
        .add_action_row(incident_btn, link_btn)
        .build()
    )

    layout = discord.ui.LayoutView()
    layout.add_item(status_card)
    layout.add_item(incident_card)
    await ctx.send(view=layout)


# ─── !profile — section with thumbnail + buttons ─────────────────────────────

@bot.command(name="profile")
async def profile_command(ctx: commands.Context):
    follow_btn  = discord.ui.Button(label="Follow",  style=discord.ButtonStyle.primary,   emoji="➕")
    message_btn = discord.ui.Button(label="Message", style=discord.ButtonStyle.secondary, emoji="💬")

    async def follow_cb(interaction: discord.Interaction):
        follow_btn.label    = "Following ✓"
        follow_btn.disabled = True
        follow_btn.style    = discord.ButtonStyle.success
        await interaction.response.edit_message(view=interaction.message.components)

    async def message_cb(interaction: discord.Interaction):
        await interaction.response.send_message("Sliding into DMs… (demo only 😄)", ephemeral=True)

    follow_btn.callback  = follow_cb
    message_btn.callback = message_cb

    profile_section = discord.ui.Section(
        discord.ui.TextDisplay("## 🧑‍💻 Developer Profile"),
        discord.ui.TextDisplay("**Name:** Jane Dev\n**Role:** Core Maintainer\n**Joined:** Jan 2023"),
        accessory=discord.ui.Thumbnail("https://cdn.discordapp.com/embed/avatars/0.png"),
    )

    container = (
        ContainerBuilder(accent_colour=0xFEE75C)
        .add_item(profile_section)
        .add_separator()
        .add_action_row(follow_btn, message_btn)
        .build()
    )

    layout = discord.ui.LayoutView()
    layout.add_item(container)
    await ctx.send(view=layout)


# ─── Startup ─────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Ready — try !card, !status, !profile")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        raise RuntimeError(
            "Set the DISCORD_TOKEN environment variable before running.\n"
            "  export DISCORD_TOKEN='your-bot-token-here'"
        )
    bot.run(TOKEN)
