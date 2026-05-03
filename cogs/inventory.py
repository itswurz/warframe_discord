# cogs/inventory.py
# ─────────────────────────────────────────────────────────────────────────────
# Dynamic inventory viewer and item description command.
#
# Commands:
#   !inventory [user]   — Browse own or another user's inventory with
#                         live filter + pagination buttons.
#   !item <name>        — Show a full item description card for any mod,
#                         resource, or cosmetic. If the user owns the item,
#                         their UUID instances are listed.
#
# Item DB:
#   Loaded once from  data/item_descriptions.json  at import time.
#   Update the JSON to add new items — no code changes required.
#
# View lifetime:
#   Views time out after 180 s of inactivity (configurable via TIMEOUT).
#   All interaction guards ensure only the original invoker can operate
#   their own inventory panel.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
import traceback
from typing import Optional

import discord
from discord.ext import commands

from data import persistence
from utils.inventory_embeds import (
    build_display_items,
    apply_filter,
    build_inventory_embed,
    build_item_embed,
    FILTER_LABELS,
    PAGE_SIZE,
)

log = logging.getLogger(__name__)

# ── Load item DB once ─────────────────────────────────────────────────────────
_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "item_descriptions.json")

_ITEM_DB_LOAD_ERROR: str | None = None   # set if the DB failed to load


def _load_item_db() -> dict:
    global _ITEM_DB_LOAD_ERROR
    try:
        with open(_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        log.info("[inventory] item_descriptions.json loaded (%d mods, %d resources, %d cosmetics)",
                 len(data.get("mods", {})),
                 len(data.get("resources", {})),
                 len(data.get("cosmetics", {})))
        return data
    except FileNotFoundError:
        _ITEM_DB_LOAD_ERROR = (
            f"Item database not found at `{_DB_PATH}`. "
            "Inventory will show items without descriptions."
        )
        log.warning("[inventory] item_descriptions.json not found — using empty DB.")
        return {"mods": {}, "resources": {}, "cosmetics": {}}
    except json.JSONDecodeError as exc:
        _ITEM_DB_LOAD_ERROR = (
            f"Item database is malformed (JSON error: {exc}). "
            "Inventory will show items without descriptions."
        )
        log.error("[inventory] item_descriptions.json JSON error: %s", exc)
        return {"mods": {}, "resources": {}, "cosmetics": {}}
    except Exception as exc:
        _ITEM_DB_LOAD_ERROR = f"Unexpected error loading item database: {exc}"
        log.exception("[inventory] Unexpected error loading item_descriptions.json")
        return {"mods": {}, "resources": {}, "cosmetics": {}}


ITEM_DB: dict = _load_item_db()

TIMEOUT = 180   # seconds before the view deactivates


# ── Shared interaction error helper ───────────────────────────────────────────

async def _interaction_error(
    interaction: discord.Interaction,
    message: str,
    *,
    ephemeral: bool = True,
) -> None:
    """
    Send an error reply to an interaction whether or not it has already been
    responded to. Never raises — swallows any secondary failure silently.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)
    except Exception:
        log.exception("[inventory] Failed to send interaction error reply.")


# ─────────────────────────────────────────────────────────────────────────────
# Filter select menu
# ─────────────────────────────────────────────────────────────────────────────

class FilterSelect(discord.ui.Select):
    """Dropdown to switch the active inventory filter."""

    def __init__(self, current_filter: str):
        options = [
            discord.SelectOption(
                label="All Items",
                value="all",
                emoji="📦",
                default=(current_filter == "all"),
            ),
            discord.SelectOption(
                label="Mods — All",
                value="mods",
                emoji="<:damage:1499651176419950622>",
                default=(current_filter == "mods"),
            ),
            discord.SelectOption(
                label="Mods — Common",
                value="mods_common",
                emoji="<:common:1499767200410636351>",
                default=(current_filter == "mods_common"),
            ),
            discord.SelectOption(
                label="Mods — Uncommon",
                value="mods_uncommon",
                emoji="<:uncommon:1499767231926636705>",
                default=(current_filter == "mods_uncommon"),
            ),
            discord.SelectOption(
                label="Mods — Rare",
                value="mods_rare",
                emoji="<:rare:1499767261236297899>",
                default=(current_filter == "mods_rare"),
            ),
            discord.SelectOption(
                label="Resources",
                value="resources",
                emoji="<:ferrite:1499750270199009320>",
                default=(current_filter == "resources"),
            ),
            discord.SelectOption(
                label="Endo",
                value="endo",
                emoji="<:endo:1499750353002954792>",
                default=(current_filter == "endo"),
            ),
            discord.SelectOption(
                label="Cosmetics",
                value="cosmetics",
                emoji="🎨",
                default=(current_filter == "cosmetics"),
            ),
        ]
        super().__init__(
            custom_id="inv_filter",
            placeholder="Filter by category…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: InventoryView = self.view   # type: ignore[assignment]

        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "This inventory panel belongs to someone else, Tenno.",
                ephemeral=True,
            )
            return

        try:
            view.filter_key = self.values[0]
            view.page       = 1
            await view._refresh(interaction)
        except Exception as exc:
            log.exception("[inventory] FilterSelect callback error for user %s", interaction.user.id)
            await _interaction_error(
                interaction,
                f"<:wf_lotus:1499651243101126816> Ordis encountered an error applying that filter.\n"
                f"```{type(exc).__name__}: {exc}```",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Navigation buttons
# ─────────────────────────────────────────────────────────────────────────────

class PrevButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="◀ Prev",
            custom_id="inv_prev",
            disabled=disabled,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: InventoryView = self.view   # type: ignore[assignment]
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "This inventory panel belongs to someone else, Tenno.",
                ephemeral=True,
            )
            return
        try:
            view.page = max(1, view.page - 1)
            await view._refresh(interaction)
        except Exception as exc:
            log.exception("[inventory] PrevButton error for user %s", interaction.user.id)
            await _interaction_error(
                interaction,
                f"<:wf_lotus:1499651243101126816> Ordis failed to turn the page.\n"
                f"```{type(exc).__name__}: {exc}```",
            )


class NextButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Next ▶",
            custom_id="inv_next",
            disabled=disabled,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: InventoryView = self.view   # type: ignore[assignment]
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "This inventory panel belongs to someone else, Tenno.",
                ephemeral=True,
            )
            return
        try:
            total_pages = view._total_pages()
            view.page = min(total_pages, view.page + 1)
            await view._refresh(interaction)
        except Exception as exc:
            log.exception("[inventory] NextButton error for user %s", interaction.user.id)
            await _interaction_error(
                interaction,
                f"<:wf_lotus:1499651243101126816> Ordis failed to turn the page.\n"
                f"```{type(exc).__name__}: {exc}```",
            )


class PageIndicatorButton(discord.ui.Button):
    """Non-interactive page counter shown between Prev / Next."""

    def __init__(self, label: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            custom_id="inv_page_indicator",
            disabled=True,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        pass


class RefreshButton(discord.ui.Button):
    """Re-fetches the player profile from disk — catches any updates."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="🔄 Refresh",
            custom_id="inv_refresh",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: InventoryView = self.view   # type: ignore[assignment]
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "This inventory panel belongs to someone else, Tenno.",
                ephemeral=True,
            )
            return
        try:
            view.profile = await persistence.load_player(view.target_id)
            view._rebuild_items()
            view.page = 1
            await view._refresh(interaction)
        except Exception as exc:
            log.exception("[inventory] RefreshButton error for user %s", interaction.user.id)
            await _interaction_error(
                interaction,
                f"<:wf_lotus:1499651243101126816> Ordis failed to refresh your inventory.\n"
                f"```{type(exc).__name__}: {exc}```",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Inventory View
# ─────────────────────────────────────────────────────────────────────────────

class InventoryView(discord.ui.View):
    """
    Persistent inventory panel for one user.

    State carried inside the view:
      owner_id     — Discord user who can interact
      target_id    — Discord user whose inventory is shown (may differ for !inv @user)
      target_name  — Display name for the target
      profile      — Loaded player profile dict
      filter_key   — Active filter ("all"|"mods"|…)
      page         — 1-indexed current page
      _all_items   — Full flat item list (rebuilt on Refresh)
    """

    def __init__(
        self,
        owner_id:    int,
        target_id:   int,
        target_name: str,
        profile:     dict,
        filter_key:  str = "all",
        page:        int = 1,
    ):
        super().__init__(timeout=TIMEOUT)
        self.owner_id    = owner_id
        self.target_id   = target_id
        self.target_name = target_name
        self.profile     = profile
        self.filter_key  = filter_key
        self.page        = page

        self._all_items: list[dict] = []
        self._rebuild_items()
        self._rebuild_buttons()

    def _rebuild_items(self) -> None:
        try:
            self._all_items = build_display_items(self.profile, ITEM_DB)
        except Exception:
            log.exception("[inventory] _rebuild_items failed for target %s", self.target_id)
            self._all_items = []

    def _filtered_items(self) -> list[dict]:
        try:
            return apply_filter(self._all_items, self.filter_key)
        except Exception:
            log.exception("[inventory] apply_filter failed (filter=%s)", self.filter_key)
            return []

    def _total_pages(self) -> int:
        filtered = self._filtered_items()
        return max(1, -(-len(filtered) // PAGE_SIZE))   # ceiling division

    def _rebuild_buttons(self) -> None:
        """Reconstruct child items so disabled states are accurate."""
        self.clear_items()

        total_pages = self._total_pages()

        # Row 0 — filter select
        self.add_item(FilterSelect(self.filter_key))

        # Row 1 — prev / indicator / next / refresh
        self.add_item(PrevButton(disabled=(self.page <= 1)))
        self.add_item(PageIndicatorButton(f"{self.page} / {total_pages}"))
        self.add_item(NextButton(disabled=(self.page >= total_pages)))
        self.add_item(RefreshButton())

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Rebuild the embed and view, then edit the message."""
        try:
            self._rebuild_buttons()
            filtered    = self._filtered_items()
            total_pages = self._total_pages()

            embed = build_inventory_embed(
                profile     = self.profile,
                items       = filtered,
                page        = self.page,
                total_pages = total_pages,
                filter_key  = self.filter_key,
                owner_name  = self.target_name,
                is_self     = (self.owner_id == self.target_id),
            )
            await interaction.response.edit_message(embed=embed, view=self)

        except discord.NotFound:
            # Message was deleted or interaction token expired — nothing to do
            log.warning("[inventory] _refresh: message not found (deleted or token expired).")

        except discord.HTTPException as exc:
            log.error("[inventory] _refresh HTTP error: %s", exc)
            await _interaction_error(
                interaction,
                "<:wf_lotus:1499651243101126816> Ordis had trouble sending the inventory panel. "
                "Please try again.",
            )

        except Exception as exc:
            log.exception("[inventory] _refresh unexpected error for target %s", self.target_id)
            await _interaction_error(
                interaction,
                f"<:wf_lotus:1499651243101126816> Ordis encountered an unexpected error.\n"
                f"```{type(exc).__name__}: {exc}```",
            )

    async def on_timeout(self) -> None:
        """Disable all buttons when the view expires."""
        for child in self.children:
            child.disabled = True   # type: ignore[union-attr]
        # Note: we can't edit the message here without storing the message ref.
        # Timeout is handled gracefully — buttons grey out on next interaction.


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class InventoryCog(commands.Cog, name="Inventory"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Warn in console if the item DB is unavailable so it's obvious
        if _ITEM_DB_LOAD_ERROR:
            log.warning("[inventory] Item DB warning: %s", _ITEM_DB_LOAD_ERROR)

    # ── !inventory ────────────────────────────────────────────────────────────

    @commands.command(name="inventory", aliases=["inv", "stash", "loadout_inv"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def inventory_cmd(
        self,
        ctx:  commands.Context,
        user: Optional[discord.Member] = None,
    ) -> None:
        """
        Browse your own (or another Tenno's) inventory.

        Usage:
          !inventory          — view your own inventory
          !inventory @Tenno   — view another Tenno's inventory
        """
        try:
            target      = user or ctx.author
            owner_id    = ctx.author.id
            target_id   = target.id
            target_name = target.display_name

            try:
                profile = await persistence.load_player(target_id)
            except Exception as exc:
                log.exception("[inventory] load_player failed for user %s", target_id)
                await ctx.send(
                    "<:wf_lotus:1499651243101126816> Ordis could not access the player database. "
                    f"Please try again later.\n```{type(exc).__name__}: {exc}```",
                    delete_after=15,
                )
                return

            # Warn if the item DB is missing — inventory still works, just no descriptions
            db_warning = (
                f"\n⚠️ *{_ITEM_DB_LOAD_ERROR}*" if _ITEM_DB_LOAD_ERROR else ""
            )

            try:
                all_items = build_display_items(profile, ITEM_DB)
            except Exception as exc:
                log.exception("[inventory] build_display_items failed for user %s", target_id)
                await ctx.send(
                    "<:wf_lotus:1499651243101126816> Ordis failed to read the inventory data. "
                    f"Your profile may be corrupted.\n```{type(exc).__name__}: {exc}```",
                    delete_after=15,
                )
                return

            total_pages = max(1, -(-len(all_items) // PAGE_SIZE))

            try:
                embed = build_inventory_embed(
                    profile     = profile,
                    items       = all_items,
                    page        = 1,
                    total_pages = total_pages,
                    filter_key  = "all",
                    owner_name  = target_name,
                    is_self     = (owner_id == target_id),
                )
            except Exception as exc:
                log.exception("[inventory] build_inventory_embed failed for user %s", target_id)
                await ctx.send(
                    "<:wf_lotus:1499651243101126816> Ordis failed to build the inventory panel. "
                    f"Please try again.\n```{type(exc).__name__}: {exc}```",
                    delete_after=15,
                )
                return

            try:
                view = InventoryView(
                    owner_id    = owner_id,
                    target_id   = target_id,
                    target_name = target_name,
                    profile     = profile,
                )
            except Exception as exc:
                log.exception("[inventory] InventoryView init failed for user %s", target_id)
                await ctx.send(
                    "<:wf_lotus:1499651243101126816> Ordis failed to build the inventory panel. "
                    f"Please try again.\n```{type(exc).__name__}: {exc}```",
                    delete_after=15,
                )
                return

            header = (
                f"<:wf_lotus:1499651243101126816> **{target_name}'s** Tenno inventory."
                if target_id != owner_id
                else "<:wf_lotus:1499651243101126816> Your Tenno inventory, Operator."
            )

            await ctx.send(
                content=header + db_warning,
                embed=embed,
                view=view,
            )

        except Exception as exc:
            log.exception("[inventory] Unhandled error in inventory_cmd for user %s", ctx.author.id)
            await ctx.send(
                "<:wf_lotus:1499651243101126816> An unexpected error occurred opening the inventory. "
                f"Ordis apologises.\n```{type(exc).__name__}: {exc}```",
                delete_after=20,
            )

    @inventory_cmd.error
    async def inventory_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Ordis is sorting the cargo bay. "
                f"Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        elif isinstance(error, commands.BadArgument):
            # e.g. user typed a non-member mention
            await ctx.send(
                "<:wf_lotus:1499651243101126816> Tenno not found. "
                "Mention a valid server member, or use `!inventory` with no arguments.",
                delete_after=8,
            )
        else:
            log.exception("[inventory] inventory_cmd unhandled framework error: %s", error)
            await ctx.send(
                "<:wf_lotus:1499651243101126816> Ordis encountered an unexpected error. "
                f"```{type(error).__name__}: {error}```",
                delete_after=20,
            )

    # ── !item ─────────────────────────────────────────────────────────────────

    @commands.command(name="item", aliases=["inspect", "codex_item", "find"])
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def item_cmd(self, ctx: commands.Context, *, name: str) -> None:
        """
        Display a full item description for any mod, resource, or cosmetic.

        Usage:
          !item Vitality
          !item Serration
          !item Ferrite
          !item "Sand Yellow Pigment"

        If you own the item, your UUID instances are shown.
        """
        try:
            if _ITEM_DB_LOAD_ERROR:
                await ctx.send(
                    f"<:wf_lotus:1499651243101126816> ⚠️ {_ITEM_DB_LOAD_ERROR}",
                    delete_after=12,
                )
                return

            try:
                profile = await persistence.load_player(ctx.author.id)
            except Exception as exc:
                log.exception("[inventory] item_cmd: load_player failed for user %s", ctx.author.id)
                await ctx.send(
                    "<:wf_lotus:1499651243101126816> Ordis could not access the player database. "
                    f"Please try again later.\n```{type(exc).__name__}: {exc}```",
                    delete_after=15,
                )
                return

            try:
                embed = build_item_embed(name.strip(), ITEM_DB, profile)
            except Exception as exc:
                log.exception("[inventory] build_item_embed failed for item %r", name)
                await ctx.send(
                    f"<:wf_lotus:1499651243101126816> Ordis failed to build the item card for **`{name}`**. "
                    f"```{type(exc).__name__}: {exc}```",
                    delete_after=15,
                )
                return

            if embed is None:
                # Item not found — offer fuzzy suggestions
                suggestions = _fuzzy_suggest(name.strip(), ITEM_DB, limit=5)
                if suggestions:
                    sugg_str = "\n".join(f"  • **{s}**" for s in suggestions)
                    await ctx.send(
                        f"<:wf_lotus:1499651243101126816> "
                        f"**`{name}`** not found in the Ordis database.\n"
                        f"Did you mean one of these?\n{sugg_str}",
                        delete_after=15,
                    )
                else:
                    await ctx.send(
                        f"<:wf_lotus:1499651243101126816> "
                        f"**`{name}`** is not in the Ordis item database, Operator.\n"
                        f"Check the spelling or try `!inventory` to browse what you own.",
                        delete_after=10,
                    )
                return

            await ctx.send(embed=embed)

        except Exception as exc:
            log.exception("[inventory] Unhandled error in item_cmd for user %s", ctx.author.id)
            await ctx.send(
                "<:wf_lotus:1499651243101126816> An unexpected error occurred looking up that item. "
                f"```{type(exc).__name__}: {exc}```",
                delete_after=20,
            )

    @item_cmd.error
    async def item_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Ordis is cross-referencing the codex. "
                f"Try again in `{error.retry_after:.1f}s`, Tenno.",
                delete_after=5,
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "<:wf_lotus:1499651243101126816> Please provide an item name. "
                "Example: `!item Vitality`",
                delete_after=8,
            )
        else:
            log.exception("[inventory] item_cmd unhandled framework error: %s", error)
            await ctx.send(
                "<:wf_lotus:1499651243101126816> Ordis encountered an unexpected error. "
                f"```{type(error).__name__}: {error}```",
                delete_after=20,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Fuzzy suggestion helper
# ─────────────────────────────────────────────────────────────────────────────

def _fuzzy_suggest(query: str, item_db: dict, limit: int = 5) -> list[str]:
    """
    Return up to `limit` item names that contain the query as a substring
    (case-insensitive). Searches mods, resources, cosmetics.
    """
    q = query.lower()
    matches: list[str] = []
    for section in ("mods", "resources", "cosmetics"):
        for key in item_db.get(section, {}):
            if q in key.lower():
                matches.append(key)
    return matches[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InventoryCog(bot))
