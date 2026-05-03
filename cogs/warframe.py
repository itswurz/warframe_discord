# cogs/warframe.py
# ─────────────────────────────────────────────────────────────────────────────
# !warframe command — three modes:
#
#   BASE  (no subcommand)
#     MODE 1 — TUTORIAL  (profile["initialized"] == False)
#       First-time flow: Choose Warframe → Choose Weapons → Fight.
#     MODE 2 — ORBITER  (profile["initialized"] == True)
#       Warframe management interface showing owned Warframes.
#
#   SUBCOMMANDS:
#     !warframe equip    <id>   — Set a Warframe active (owner only)
#     !warframe view     <id>   — Inspect any Warframe by ID (any user)
#     !warframe sell     <id>   — Sell an owned Warframe (owner only, not last)
#     !warframe mods     <id>   — Open the mod configuration panel for a
#                                 Warframe the player owns (by instance ID)
#
# Sell economy:
#   Base value: 500 Credits + 100 Credits per level.
#   A level-30 Warframe is worth 3,500 Credits.
#
# Mod system:
#   !warframe mods <warframe_id>
#     • Validates that the player owns the Warframe instance.
#     • Shows only mods from the player's own mod_collection.
#     • Mods are consumed on equip — they cannot be used on multiple Warframes.
#     • Duplicate mod names on the same Warframe are blocked.
#     • Stat changes are applied immediately and shown in the header.
#
# Adding a new Warframe:
#   Add it to data/warframes.py WARFRAMES — nothing here needs changing.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import discord
from discord.ext import commands
from datetime import datetime, timezone

from data.warframes import WARFRAMES
from data import persistence
from data.persistence import (
    MAX_WARFRAME_SLOTS,
    add_warframe_to_roster,
    set_active_warframe,
    get_active_warframe_instance,
    find_warframe_by_instance_id,
    remove_warframe_from_roster,
)
from data.polarity import warframe_slot_polarities
from utils.embeds import build_entry_embed, build_warframe_embed
from utils.polarity_embeds import slot_row
from utils.mods_ui import build_mods_layout, get_wf_instance
from utils.emojis import E


# ── Colour palette ─────────────────────────────────────────────────────────────
_COLOR_DEFAULT  = 0x1F4E5F
_COLOR_ACTIVE   = 0x1A7A3C   # green — active slot
_COLOR_EMPTY    = 0x2C2F33   # dark  — empty slot
_COLOR_DANGER   = 0x7B1515   # red   — destructive actions
_COLOR_GOLD     = 0xC8A951   # gold  — sell confirmation

# ── Level / XP constants ───────────────────────────────────────────────────────
_MAX_LEVEL   = 30
_XP_PER_LVL  = 1000

# ── Sell economy ───────────────────────────────────────────────────────────────
_SELL_BASE      = 500    # base credits for any Warframe
_SELL_PER_LEVEL = 100    # additional credits per level (max 3,000 at level 30)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sell_price(level: int) -> int:
    """Calculate credit value for selling a Warframe at the given level."""
    return _SELL_BASE + max(0, int(level)) * _SELL_PER_LEVEL


def _xp_bar(xp: int, level: int, length: int = 8) -> str:
    if level >= _MAX_LEVEL:
        return f"{'█' * length} **MAX**"
    needed = _XP_PER_LVL
    ratio  = min(1.0, xp / needed)
    filled = round(ratio * length)
    return f"{'█' * filled}{'░' * (length - filled)}"


def _level_bar(level: int, length: int = 10) -> str:
    filled = round((level / _MAX_LEVEL) * length)
    return f"{'█' * filled}{'░' * (length - filled)}"


def _stat_line(wf_data: dict, key: str, icon: str) -> str:
    """Pull a stat from the warframe codex and return a compact line."""
    stats = wf_data.get("stats", {})
    for k, v in stats.items():
        if k.endswith(key) or k == key:
            base = v.split("→")[0].strip().split()[0]
            return f"{icon} **{base}**"
    return f"{icon} —"


def _parse_acquired(acquired: str) -> str:
    """Convert ISO-8601 timestamp to a short YYYY-MM-DD string."""
    try:
        dt = datetime.fromisoformat(acquired.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "—"


def _normalise_id(raw: str) -> str:
    """Normalise a Warframe instance ID to uppercase, stripping whitespace."""
    return raw.strip().upper()


def _equipped_mod_count(wf_instance: dict) -> int:
    """Count how many slots have a mod equipped on this warframe instance."""
    em = wf_instance.get("equipped_mods", {})
    return sum(1 for v in em.values() if v is not None)


def _modded_stat_lines(wf_instance: dict, profile: dict) -> tuple[str, str, str, str, list]:
    """
    Return (hp_line, shld_line, armor_line, energy_line) strings that reflect
    the warframe's actual stats after all equipped mods are applied.

    When mods boost a stat, the line shows  base → final  so the delta is
    immediately visible.  When no mods are equipped (or the call fails) the
    lines fall back to the plain base-stat strings from _stat_line().

    Returns a 4-tuple of Discord-formatted strings ready to embed.
    """
    wf_key  = wf_instance.get("warframe_key", "")
    wf_data = WARFRAMES.get(wf_key, {})

    # Pull base values from the codex display strings (same as _stat_line)
    def _base(key: str) -> int:
        stats = wf_data.get("stats", {})
        for k, v in stats.items():
            if k.endswith(key) or k == key:
                try:
                    return int(v.split("→")[0].strip().split()[0])
                except (ValueError, IndexError):
                    return 0
        return 0

    base_hp     = _base("Health")
    base_sh     = _base("Shields")
    base_ar     = _base("Armor")
    base_en     = _base("Energy")

    # Try to get mod-boosted finals
    final_hp  = base_hp
    final_sh  = base_sh
    final_ar  = base_ar
    final_en  = base_en
    extra_lines: list[str] = []

    try:
        from utils.mods_ui import get_active_stat_bonuses
        ms = get_active_stat_bonuses(profile, wf_instance)
        final_hp = ms.get("health",  base_hp)
        final_sh = ms.get("shields", base_sh)
        final_ar = ms.get("armor",   base_ar)
        final_en = ms.get("energy",  base_en)

        # Collect extra bonuses for a compact footer note
        if ms.get("ability_efficiency_bonus"):
            extra_lines.append(f"-{ms['ability_efficiency_bonus']}% ability cost")
        if ms.get("puncture_resist_bonus"):
            extra_lines.append(f"+{ms['puncture_resist_bonus']}% Puncture resist")
        if ms.get("knockdown_chance_bonus"):
            extra_lines.append(f"+{ms['knockdown_chance_bonus']}% KD chance")
        if ms.get("loot_bonus"):
            extra_lines.append(f"+{ms['loot_bonus']}% loot")
        if ms.get("electricity_store_bonus"):
            extra_lines.append(f"+{ms['electricity_store_bonus']}% arc store")
    except Exception:
        pass   # graceful fallback to base stats

    def _fmt(icon: str, base: int, final: int) -> str:
        if final != base and base > 0:
            return f"{icon} **{final}** *(+{final - base})*"
        return f"{icon} **{final}**"

    hp_line     = _fmt("<a:health:1499636458309423215>",              base_hp, final_hp)
    shld_line   = _fmt(E.shield,            base_sh, final_sh)
    armor_line  = _fmt(E.defense,     base_ar, final_ar)
    energy_line = _fmt("<a:energy_orb:1499636329842212964>",          base_en, final_en)

    return hp_line, shld_line, armor_line, energy_line, extra_lines


# ─────────────────────────────────────────────────────────────────────────────
# Orbiter embed builder
# ─────────────────────────────────────────────────────────────────────────────

def build_orbiter_embed(profile: dict) -> discord.Embed:
    """Build the Orbiter management embed showing all Warframe slots."""
    roster    = profile.get("warframe_roster", [])
    mr        = profile.get("mastery_rank", 0)
    credits_  = profile.get("credits", 0)
    missions  = profile.get("total_missions", 0)
    kills     = profile.get("total_kills", 0)

    embed = discord.Embed(
        title=f"{E.lotus}  ORBITER",
        description=(
            f"{E.lotus} **Mastery Rank {mr}**  ·  "
            f"{E.credits} `{credits_:,}` Credits  ·  "
            f"`{missions}` Missions  ·  "
            f"`{kills}` Kills"
        ),
        color=_COLOR_DEFAULT,
    )

    for slot_idx in range(MAX_WARFRAME_SLOTS):
        slot_num  = slot_idx + 1
        slot_name = f"WARFRAME SLOT {slot_num}"

        if slot_idx < len(roster):
            wf        = roster[slot_idx]
            wf_key    = wf["warframe_key"]
            wf_name   = wf["warframe_name"]
            wf_data   = WARFRAMES.get(wf_key, {})
            level     = wf.get("level", 0)
            xp        = wf.get("xp", 0)
            wf_id     = wf["instance_id"]
            is_active = wf.get("is_active", False)
            acquired  = wf.get("acquired_at", "")
            emoji     = wf_data.get("emoji", "")
            mod_count = _equipped_mod_count(wf)

            date_str    = _parse_acquired(acquired)
            hp_line, shld_line, armor_line, energy_line, extra_bonuses = \
                _modded_stat_lines(wf, profile)

            active_tag = "  🟢 **ACTIVE**" if is_active else ""
            lvl_bar    = _level_bar(level)
            xp_bar     = _xp_bar(xp, level)
            sell_val   = _sell_price(level)
            mod_tag    = f"{mod_count}/8 mods" if mod_count else "No mods equipped"
            bonus_tag  = f"  ·  {', '.join(extra_bonuses)}" if extra_bonuses else ""

            value = (
                f"{emoji} **{wf_name}**{active_tag}\n"
                f"{E.combo} `ID: {wf_id}`  ·  Acquired {date_str}\n"
                f"\n"
                f"**Level** {level}/{_MAX_LEVEL}  `{lvl_bar}`\n"
                f"**XP**  {xp}/{_XP_PER_LVL if level < _MAX_LEVEL else '—'}  `{xp_bar}`\n"
                f"\n"
                f"{hp_line}   {shld_line}   {armor_line}   {energy_line}{bonus_tag}\n"
                f"{E.location} **Mods:** {mod_tag}\n"
                f"\n"
                f"**Sell Value:** {E.credits} `{sell_val:,}` Credits  ·  `!warframe sell {wf_id}` to dispose\n"
                f"**Mods:** `!warframe mods {wf_id}` to configure\n"
                f"*{wf_data.get('lore', '—')[:80]}"
                f"{'…' if len(wf_data.get('lore', '')) > 80 else ''}*"
            )
            embed.add_field(name=slot_name, value=value, inline=False)

        else:
            embed.add_field(
                name=f"WARFRAME SLOT {slot_num}  ·  🔒 Locked",
                value=(
                    "*This slot is empty. Acquire a new Warframe to fill it.*\n"
                    "Use the **Add Warframe** button to expand your roster."
                ),
                inline=False,
            )

    embed.set_footer(
        text=(
            f"Orbiter  ·  {len(roster)}/{MAX_WARFRAME_SLOTS} Warframe slots used  ·  "
            f"!warframe equip <ID> · !warframe mods <ID> · !warframe sell <ID>  ·  "
            f"Warframe © Digital Extremes"
        )
    )
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Warframe detail embed  (!warframe view)
# ─────────────────────────────────────────────────────────────────────────────

def _build_warframe_view_embed(
    instance:   dict,
    wf_data:    dict,
    owner_name: str,
    is_self:    bool,
    profile:    dict | None = None,
) -> discord.Embed:
    """Full detail embed for a single Warframe instance."""
    wf_name   = instance["warframe_name"]
    wf_key    = instance["warframe_key"]
    inst_id   = instance["instance_id"]
    level     = instance.get("level", 0)
    xp        = instance.get("xp", 0)
    acquired  = instance.get("acquired_at", "")
    is_active = instance.get("is_active", False)
    emoji     = wf_data.get("emoji", "")
    color     = wf_data.get("color", _COLOR_DEFAULT)
    mod_count = _equipped_mod_count(instance)

    active_tag = "  🟢 **ACTIVE**" if is_active else "  ⬛ Inactive"
    date_str   = _parse_acquired(acquired)
    lvl_bar    = _level_bar(level)
    xp_bar     = _xp_bar(xp, level)
    sell_val   = _sell_price(level)

    embed = discord.Embed(
        title=f"{emoji}  {wf_name}",
        description=f"*{wf_data.get('lore', '—')[:160]}*",
        color=color,
    )
    embed.set_author(
        name=f"{wf_data.get('role', 'Warframe')}  ·  ID: {inst_id}"
    )

    thumb = wf_data.get("thumbnail_url") or wf_data.get("icon_url")
    if thumb:
        embed.set_thumbnail(url=thumb)

    embed.add_field(
        name="LEVEL",
        value=(
            f"**{level}** / {_MAX_LEVEL}  `{lvl_bar}`\n"
            f"XP: **{xp:,}** / "
            f"{'—' if level >= _MAX_LEVEL else f'{_XP_PER_LVL:,}'}  "
            f"`{xp_bar}`"
        ),
        inline=False,
    )

    # Use modded stats when a profile is available, fall back to base otherwise
    if profile is not None:
        hp_line, shld_line, armor_line, energy_line, extra_bonuses = \
            _modded_stat_lines(instance, profile)
        stat_label = "STATS" + (" *(with mods)*" if mod_count else "")
    else:
        hp_line     = _stat_line(wf_data, "Health",  "<a:health:1499636458309423215>")
        shld_line   = _stat_line(wf_data, "Shields", E.shield)
        armor_line  = _stat_line(wf_data, "Armor",   E.defense)
        energy_line = _stat_line(wf_data, "Energy",  "<a:energy_orb:1499636329842212964>")
        extra_bonuses = []
        stat_label = "BASE STATS"

    stat_value = f"{hp_line}   {shld_line}   {armor_line}   {energy_line}"
    if extra_bonuses:
        stat_value += f"\n{', '.join(extra_bonuses)}"

    embed.add_field(name=stat_label, value=stat_value, inline=False)

    passive = wf_data.get("passive", "—")
    embed.add_field(
        name="PASSIVE",
        value=passive[:300] + ("…" if len(passive) > 300 else ""),
        inline=False,
    )

    slots     = warframe_slot_polarities(wf_key)
    slots_str = slot_row(slots)
    embed.add_field(
        name=f"MOD SLOTS  ({len(slots)} total  ·  {mod_count} equipped)",
        value=slots_str if slots_str.strip() else "*(no polarity data)*",
        inline=False,
    )

    own_tag = "  *(you)*" if is_self else ""
    embed.add_field(
        name="OWNERSHIP",
        value=(
            f"**Owner:** {owner_name}{own_tag}\n"
            f"**Acquired:** {date_str}\n"
            f"**Status:** {active_tag}\n"
            f"**Sell Value:** {E.credits} `{sell_val:,}` Credits"
        ),
        inline=False,
    )

    if is_self:
        hint = (
            f"!warframe equip {inst_id} to activate  ·  "
            f"!warframe mods {inst_id} to configure mods  ·  "
            f"!warframe sell {inst_id} to sell"
        )
    else:
        hint = "You can view any Tenno's Warframe — only the owner can equip, mod, or sell"

    embed.set_footer(
        text=f"ID: {inst_id}  ·  {hint}  ·  Warframe © Digital Extremes"
    )
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Sell confirmation embed
# ─────────────────────────────────────────────────────────────────────────────

def _build_sell_confirm_embed(
    instance: dict,
    wf_data:  dict,
    is_last:  bool,
) -> discord.Embed:
    wf_name  = instance["warframe_name"]
    inst_id  = instance["instance_id"]
    level    = instance.get("level", 0)
    emoji    = wf_data.get("emoji", "")
    sell_val = _sell_price(level)
    mod_count = _equipped_mod_count(instance)

    if is_last:
        embed = discord.Embed(
            title=f"{E.lotus}  Cannot Sell Last Warframe",
            description=(
                f"{emoji} **{wf_name}** `[{inst_id}]` is your **only Warframe**.\n\n"
                "The Lotus forbids abandoning your last suit, Operator — "
                "you would have no means of fighting the Grineer.\n\n"
                "Acquire a second Warframe before disposing of this one."
            ),
            color=_COLOR_DANGER,
        )
        embed.set_footer(text="Acquisition blocked — roster must have ≥ 1 Warframe at all times.")
        return embed

    mod_note = (
        f"\n\n⚠️ **{mod_count} mod(s) equipped** on this Warframe will be returned to your collection."
        if mod_count else ""
    )

    embed = discord.Embed(
        title=f"{E.lotus}  Confirm Warframe Sale",
        description=(
            f"You are about to sell {emoji} **{wf_name}** `[{inst_id}]`.\n\n"
            f"**Level:** {level} / {_MAX_LEVEL}\n"
            f"**Sale value:** {E.credits} `{sell_val:,}` Credits"
            f"{mod_note}\n\n"
            "⚠️ This action is **permanent and cannot be undone**."
        ),
        color=_COLOR_GOLD,
    )
    thumb = wf_data.get("thumbnail_url") or wf_data.get("icon_url")
    if thumb:
        embed.set_thumbnail(url=thumb)
    embed.set_footer(text="Confirm within 30 seconds, or the transaction will be cancelled.")
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Sell confirmation view
# ─────────────────────────────────────────────────────────────────────────────

class SellConfirmView(discord.ui.View):
    def __init__(
        self,
        owner_id:   int,
        instance:   dict,
        wf_data:    dict,
        sell_price: int,
    ) -> None:
        super().__init__(timeout=30)
        self.owner_id   = owner_id
        self.instance   = instance
        self.wf_data    = wf_data
        self.sell_price = sell_price

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                f"{E.lotus} This transaction belongs to another Operator.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm Sale", style=discord.ButtonStyle.danger, emoji=discord.PartialEmoji(name="credits", id=1499637105142399087), custom_id="sell_confirm")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        profile  = await persistence.load_player(self.owner_id)
        inst_id  = self.instance["instance_id"]
        roster   = profile.get("warframe_roster", [])
        wf_name  = self.instance["warframe_name"]
        wf_emoji = self.wf_data.get("emoji", "")

        if not any(w["instance_id"] == inst_id for w in roster):
            await interaction.response.edit_message(
                content=f"{E.lotus} ❌ That Warframe is no longer in your roster.",
                embed=None, view=None,
            )
            self.stop()
            return

        if len(roster) <= 1:
            await interaction.response.edit_message(
                content=f"{E.lotus} ❌ You cannot sell your last Warframe.",
                embed=None, view=None,
            )
            self.stop()
            return

        # Free all mods equipped on this warframe before removing it
        wf_inst = next((w for w in roster if w["instance_id"] == inst_id), None)
        if wf_inst:
            em = wf_inst.get("equipped_mods", {})
            for slot_data in em.values():
                if slot_data:
                    mod_uuid = slot_data.get("mod_uuid", "")
                    for m in profile.get("mod_collection", []):
                        if m["uuid"] == mod_uuid:
                            m["equipped_on_warframe"] = None
                            m["tradeable"] = True
                            break

        removed = remove_warframe_from_roster(profile, inst_id)
        if removed is None:
            await interaction.response.edit_message(
                content=f"{E.lotus} ❌ Warframe not found.",
                embed=None, view=None,
            )
            self.stop()
            return

        profile["credits"] = profile.get("credits", 0) + self.sell_price
        await persistence.save_player(profile)

        embed = build_orbiter_embed(profile)
        view  = OrbiterView(profile)

        await interaction.response.edit_message(
            content=(
                f"{E.lotus} {wf_emoji} **{wf_name}** "
                f"`[{inst_id}]` sold for **{self.sell_price:,}** {E.credits} Credits. "
                f"Balance: {E.credits} `{profile['credits']:,}` Credits."
            ),
            embed=embed, view=view,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="sell_cancel")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=(
                f"{E.lotus} Sale cancelled. "
                f"**{self.instance['warframe_name']}** remains in your roster."
            ),
            embed=None, view=None,
        )
        self.stop()

    async def on_timeout(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Tutorial flow
# ─────────────────────────────────────────────────────────────────────────────

class TutorialChooseButton(discord.ui.Button):
    def __init__(self, warframe_key: str):
        self.warframe_key = warframe_key
        wf_name = WARFRAMES[warframe_key]["name"]
        super().__init__(
            style=discord.ButtonStyle.success,
            label=f"Choose {wf_name}",
            emoji="✅",
            custom_id=f"tutorial_choose_{warframe_key}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            profile = await persistence.load_player(interaction.user.id)
            wf_name = WARFRAMES[self.warframe_key]["name"]

            existing = profile.get("warframe_roster", [])
            already  = any(w["warframe_key"] == self.warframe_key for w in existing)
            if not already:
                add_warframe_to_roster(
                    profile       = profile,
                    warframe_key  = self.warframe_key,
                    warframe_name = wf_name,
                    set_active    = True,
                )
            else:
                for w in profile["warframe_roster"]:
                    w["is_active"] = (w["warframe_key"] == self.warframe_key)
                profile["warframe"] = wf_name

            await persistence.save_player(profile)

            from cogs.weapon import WeaponView
            from utils.weapon_embeds import build_weapon_entry_embed

            embed = build_weapon_entry_embed()
            view  = WeaponView()

            await interaction.response.edit_message(
                content=(
                    f"{E.lotus} "
                    f"**{wf_name}** confirmed, Operator. Now choose your Primary weapon."
                ),
                embed=embed, view=view,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Error: `{e}`", ephemeral=True)


class TutorialBackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary, label="Back", emoji="🔙",
            custom_id="tutorial_warframe_back", row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = build_entry_embed()
        view  = TutorialWarframeView()
        await interaction.response.edit_message(embed=embed, view=view)


class TutorialWarframeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=wf["name"], value=key, description=wf["role"], emoji=wf["emoji"])
            for key, wf in WARFRAMES.items()
        ]
        super().__init__(
            custom_id="tutorial_warframe_select",
            placeholder="Browse Warframes, Tenno…",
            min_values=1, max_values=1, options=options, row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key    = self.values[0]
        player = await persistence.load_player(interaction.user.id)
        embed  = build_warframe_embed(key, player, confirmed=False)
        view   = TutorialWarframeView(preview_key=key)
        await interaction.response.edit_message(embed=embed, view=view)


class TutorialWarframeView(discord.ui.View):
    def __init__(self, preview_key: str | None = None):
        super().__init__(timeout=None)
        self.add_item(TutorialWarframeSelect())
        if preview_key:
            self.add_item(TutorialChooseButton(preview_key))
            self.add_item(TutorialBackButton())


# ─────────────────────────────────────────────────────────────────────────────
# Orbiter buttons
# ─────────────────────────────────────────────────────────────────────────────

class SetActiveButton(discord.ui.Button):
    def __init__(self, instance_id: str, warframe_name: str, slot_idx: int):
        self.instance_id = instance_id
        super().__init__(
            style=discord.ButtonStyle.success,
            label=f"Activate {warframe_name}",
            emoji="🟢",
            custom_id=f"orbiter_activate_{instance_id}",
            row=slot_idx,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        profile = await persistence.load_player(interaction.user.id)
        found   = set_active_warframe(profile, self.instance_id)

        if not found:
            await interaction.response.send_message("❌ Warframe instance not found.", ephemeral=True)
            return

        await persistence.save_player(profile)
        embed = build_orbiter_embed(profile)
        view  = OrbiterView(profile)
        await interaction.response.edit_message(embed=embed, view=view)


class AddWarframeButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            style=discord.ButtonStyle.primary, label="Add Warframe", emoji="➕",
            custom_id="orbiter_add_warframe", row=0, disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        profile = await persistence.load_player(interaction.user.id)

        if len(profile.get("warframe_roster", [])) >= MAX_WARFRAME_SLOTS:
            await interaction.response.send_message(
                f"{E.lotus} Your Warframe roster is full "
                f"({MAX_WARFRAME_SLOTS}/{MAX_WARFRAME_SLOTS} slots).",
                ephemeral=True,
            )
            return

        embed = build_entry_embed()
        view  = AcquireWarframeView()
        await interaction.response.edit_message(
            content=f"{E.lotus} Choose a Warframe to add to your roster.",
            embed=embed, view=view,
        )


class RefreshOrbiterButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary, label="Refresh", emoji="🔄",
            custom_id="orbiter_refresh", row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        profile = await persistence.load_player(interaction.user.id)
        embed   = build_orbiter_embed(profile)
        view    = OrbiterView(profile)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class OrbiterView(discord.ui.View):
    def __init__(self, profile: dict | None = None):
        super().__init__(timeout=None)
        roster  = (profile or {}).get("warframe_roster", [])
        is_full = len(roster) >= MAX_WARFRAME_SLOTS

        self.add_item(AddWarframeButton(disabled=is_full))
        self.add_item(RefreshOrbiterButton())

        for idx, wf in enumerate(roster):
            if not wf.get("is_active", False):
                btn_row = min(idx + 1, 4)
                self.add_item(
                    SetActiveButton(
                        instance_id   = wf["instance_id"],
                        warframe_name = wf["warframe_name"],
                        slot_idx      = btn_row,
                    )
                )


# ─────────────────────────────────────────────────────────────────────────────
# Acquire Warframe flow (post-init roster expansion)
# ─────────────────────────────────────────────────────────────────────────────

class AcquireConfirmButton(discord.ui.Button):
    def __init__(self, warframe_key: str):
        self.warframe_key = warframe_key
        wf_name = WARFRAMES[warframe_key]["name"]
        super().__init__(
            style=discord.ButtonStyle.success, label=f"Acquire {wf_name}", emoji="✅",
            custom_id=f"acquire_confirm_{warframe_key}", row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            profile = await persistence.load_player(interaction.user.id)
            wf_name = WARFRAMES[self.warframe_key]["name"]

            existing_keys = {w["warframe_key"] for w in profile.get("warframe_roster", [])}
            if self.warframe_key in existing_keys:
                await interaction.response.send_message(
                    f"{E.lotus} **{wf_name}** is already in your roster.",
                    ephemeral=True,
                )
                return

            if len(profile.get("warframe_roster", [])) >= MAX_WARFRAME_SLOTS:
                await interaction.response.send_message(
                    f"{E.lotus} Roster is full — no empty slots.",
                    ephemeral=True,
                )
                return

            instance = add_warframe_to_roster(
                profile=profile, warframe_key=self.warframe_key,
                warframe_name=wf_name, set_active=False,
            )
            await persistence.save_player(profile)

            embed = build_orbiter_embed(profile)
            view  = OrbiterView(profile)

            await interaction.response.edit_message(
                content=(
                    f"{E.lotus} **{wf_name}** "
                    f"`[{instance['instance_id']}]` added to your roster!"
                ),
                embed=embed, view=view,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Error: `{e}`", ephemeral=True)


class AcquireBackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary, label="Back to Orbiter", emoji="🔙",
            custom_id="acquire_back", row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        profile = await persistence.load_player(interaction.user.id)
        embed   = build_orbiter_embed(profile)
        view    = OrbiterView(profile)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class AcquireWarframeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=wf["name"], value=key, description=wf["role"], emoji=wf["emoji"])
            for key, wf in WARFRAMES.items()
        ]
        super().__init__(
            custom_id="acquire_warframe_select",
            placeholder="Choose a Warframe to add…",
            min_values=1, max_values=1, options=options, row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key    = self.values[0]
        player = await persistence.load_player(interaction.user.id)
        embed  = build_warframe_embed(key, player, confirmed=False)
        view   = AcquireWarframeView(preview_key=key)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class AcquireWarframeView(discord.ui.View):
    def __init__(self, preview_key: str | None = None):
        super().__init__(timeout=None)
        self.add_item(AcquireWarframeSelect())
        if preview_key:
            self.add_item(AcquireConfirmButton(preview_key))
            self.add_item(AcquireBackButton())


# ─────────────────────────────────────────────────────────────────────────────
# Initialization completion hook
# ─────────────────────────────────────────────────────────────────────────────

async def mark_player_initialized(user_id: int | str) -> None:
    profile = await persistence.load_player(user_id)
    if not profile.get("initialized", False):
        profile["initialized"] = True
        await persistence.save_player(profile)


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class WarframeCog(commands.Cog, name="Warframe"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(TutorialWarframeView())
        self.bot.add_view(AcquireWarframeView())
        self.bot.add_view(OrbiterView())

        for key in WARFRAMES:
            self.bot.add_view(TutorialWarframeView(preview_key=key))
            self.bot.add_view(AcquireWarframeView(preview_key=key))

    # ── Base command (group) ──────────────────────────────────────────────────

    @commands.group(
        name="warframe",
        aliases=["wf", "codex", "orbiter"],
        invoke_without_command=True,
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def warframe_cmd(self, ctx: commands.Context) -> None:
        """
        First time: Warframe selection tutorial.
        After that:  Orbiter — your Warframe management hub.

        Subcommands:
          !warframe equip <id>  — Equip a Warframe from your roster
          !warframe view  <id>  — Inspect any Warframe by instance ID
          !warframe sell  <id>  — Sell a Warframe from your roster
          !warframe mods  <id>  — Configure mods on an owned Warframe
        """
        profile = await persistence.load_player(ctx.author.id)

        if not profile.get("initialized", False):
            embed = build_entry_embed()
            view  = TutorialWarframeView()
            await ctx.send(
                content=(
                    f"{E.lotus} "
                    "*\"Welcome, Operator. Your Warframe awaits.\"*"
                ),
                embed=embed, view=view,
            )
        else:
            embed = build_orbiter_embed(profile)
            view  = OrbiterView(profile)
            await ctx.send(
                content=(
                    f"{E.lotus} "
                    f"*\"Welcome back, {ctx.author.display_name}. "
                    f"Your Orbiter is standing by.\"*"
                ),
                embed=embed, view=view,
            )

    # ── !warframe equip <id> ──────────────────────────────────────────────────

    @warframe_cmd.command(name="equip", aliases=["e", "activate", "deploy"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def warframe_equip(self, ctx: commands.Context, warframe_id: str) -> None:
        """Set one of your Warframes as the active (equipped) suit."""
        inst_id = _normalise_id(warframe_id)
        profile = await persistence.load_player(ctx.author.id)
        roster  = profile.get("warframe_roster", [])

        target = next((w for w in roster if w["instance_id"] == inst_id), None)
        if target is None:
            await ctx.send(
                f"{E.lotus} ❌ Warframe `{inst_id}` was not found "
                f"in **your** roster. Use `!warframe` to see your current roster.",
                delete_after=12,
            )
            return

        if target.get("is_active", False):
            wf_data  = WARFRAMES.get(target["warframe_key"], {})
            wf_emoji = wf_data.get("emoji", "")
            await ctx.send(
                f"{E.lotus} {wf_emoji} **{target['warframe_name']}** "
                f"`[{inst_id}]` is already your active Warframe.",
                delete_after=8,
            )
            return

        set_active_warframe(profile, inst_id)
        await persistence.save_player(profile)

        wf_data  = WARFRAMES.get(target["warframe_key"], {})
        wf_emoji = wf_data.get("emoji", "")

        embed = build_orbiter_embed(profile)
        view  = OrbiterView(profile)

        await ctx.send(
            content=(
                f"{E.lotus} {wf_emoji} **{target['warframe_name']}** "
                f"`[{inst_id}]` is now your active Warframe."
            ),
            embed=embed, view=view,
        )

    # ── !warframe view <id> ───────────────────────────────────────────────────

    @warframe_cmd.command(name="view", aliases=["v", "inspect", "info"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def warframe_view(self, ctx: commands.Context, warframe_id: str) -> None:
        """Display the full detail card for any Warframe by instance ID."""
        inst_id = _normalise_id(warframe_id)

        profile      = await persistence.load_player(ctx.author.id)
        own_roster   = profile.get("warframe_roster", [])
        own_instance = next((w for w in own_roster if w["instance_id"] == inst_id), None)

        if own_instance:
            instance   = own_instance
            owner_name = ctx.author.display_name
            is_self    = True
        else:
            async with ctx.typing():
                owner_id_str, instance = await find_warframe_by_instance_id(inst_id)

            if instance is None:
                await ctx.send(
                    f"{E.lotus} ❌ No Warframe with ID `{inst_id}` found.",
                    delete_after=12,
                )
                return

            owner_name = f"Unknown Operator (`{owner_id_str}`)"
            is_self    = False
            try:
                owner = await self.bot.fetch_user(int(owner_id_str))
                owner_name = owner.display_name
                is_self = (owner.id == ctx.author.id)
            except Exception:
                pass

        wf_key  = instance.get("warframe_key", "")
        wf_data = WARFRAMES.get(wf_key)

        if wf_data is None:
            await ctx.send(
                f"{E.lotus} ❌ Warframe codex entry for `{wf_key}` not found.",
                delete_after=10,
            )
            return

        # For own Warframes pass the full profile so mod bonuses show.
        # For another player's Warframe, synthesise a minimal profile dict
        # that contains just the instance — enough for get_active_stat_bonuses
        # to compute the final stats without loading someone else's full file.
        if is_self:
            view_profile: dict | None = profile
        else:
            view_profile = {"warframe_roster": [instance]}

        embed = _build_warframe_view_embed(
            instance=instance, wf_data=wf_data,
            owner_name=owner_name, is_self=is_self,
            profile=view_profile,
        )
        await ctx.send(embed=embed)

    # ── !warframe sell <id> ───────────────────────────────────────────────────

    @warframe_cmd.command(name="sell", aliases=["s", "dispose", "trade"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def warframe_sell(self, ctx: commands.Context, warframe_id: str) -> None:
        """Sell a Warframe from your roster for Credits."""
        inst_id = _normalise_id(warframe_id)
        profile = await persistence.load_player(ctx.author.id)
        roster  = profile.get("warframe_roster", [])

        target = next((w for w in roster if w["instance_id"] == inst_id), None)
        if target is None:
            await ctx.send(
                f"{E.lotus} ❌ Warframe `{inst_id}` is not in **your** roster.",
                delete_after=12,
            )
            return

        wf_key  = target.get("warframe_key", "")
        wf_data = WARFRAMES.get(wf_key, {})
        is_last = len(roster) <= 1

        embed = _build_sell_confirm_embed(target, wf_data, is_last)

        if is_last:
            await ctx.send(embed=embed)
            return

        level    = target.get("level", 0)
        sell_val = _sell_price(level)

        view = SellConfirmView(
            owner_id=ctx.author.id, instance=target,
            wf_data=wf_data, sell_price=sell_val,
        )

        await ctx.send(
            content=f"{E.lotus} Sale pending confirmation — 30 seconds to decide.",
            embed=embed, view=view,
        )

    # ── !warframe mods <warframe_id> ─────────────────────────────────────────

    @warframe_cmd.command(name="mods", aliases=["mod", "modifications"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def warframe_mods(
        self,
        ctx:         commands.Context,
        warframe_id: str | None = None,
    ) -> None:
        """
        Open the mod configuration panel for one of your Warframes.

        You must own the Warframe (by instance ID).
        Only mods from your own collection can be equipped.
        Equipping a mod consumes it — it cannot be used on another Warframe
        until removed. The same mod name cannot be slotted twice.

        Usage:
          !warframe mods <ID>    — open by Warframe instance ID
          !warframe mods         — uses your currently active Warframe
          !wf mods B7KQ58L
        """
        profile = await persistence.load_player(ctx.author.id)

        # ── Resolve target instance ───────────────────────────────────────────
        if warframe_id:
            inst_id  = _normalise_id(warframe_id)
            wf_inst  = get_wf_instance(profile, inst_id)
            if wf_inst is None:
                await ctx.send(
                    f"{E.lotus} ❌ Warframe `{inst_id}` not found in **your** roster.\n"
                    f"You can only configure Warframes you own. "
                    f"Use `!warframe` to see your roster and find your IDs.",
                    delete_after=14,
                )
                return
        else:
            # Fall back to active Warframe
            roster  = profile.get("warframe_roster", [])
            wf_inst = next((w for w in roster if w.get("is_active")), None)
            if wf_inst is None:
                wf_inst = roster[0] if roster else None
            if wf_inst is None:
                await ctx.send(
                    f"{E.lotus} No Warframe found in your roster. "
                    "Use `!warframe` first.",
                    delete_after=10,
                )
                return

        # ── Validate that the Warframe key exists in the mods codex ──────────
        from utils.mods_ui import _get_wf_codex
        wf_key = wf_inst.get("warframe_key", "")
        if _get_wf_codex(wf_key) is None:
            await ctx.send(
                f"{E.lotus} ❌ Mod codex entry for `{wf_key}` not found. "
                "The warframes_mods.json may need updating.",
                delete_after=10,
            )
            return

        layout = build_mods_layout(ctx.author.id, profile, wf_inst)

        await ctx.send(view=layout)

    # ── Error handlers ────────────────────────────────────────────────────────

    @warframe_cmd.error
    async def warframe_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Ordis is recalibrating. Try again in `{error.retry_after:.1f}s`.",
                delete_after=5,
            )
        elif isinstance(error, commands.CommandNotFound):
            await ctx.invoke(self.warframe_cmd)
        else:
            raise error

    @warframe_equip.error
    async def equip_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"{E.lotus} Please provide a Warframe ID.\n"
                "Usage: `!warframe equip <ID>`  e.g. `!warframe equip B7KQ58L`",
                delete_after=12,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error

    @warframe_view.error
    async def view_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"{E.lotus} Please provide a Warframe ID.\n"
                "Usage: `!warframe view <ID>`  e.g. `!warframe view B7KQ58L`",
                delete_after=12,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error

    @warframe_sell.error
    async def sell_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"{E.lotus} Please provide a Warframe ID.\n"
                "Usage: `!warframe sell <ID>`  e.g. `!warframe sell B7KQ58L`",
                delete_after=12,
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error

    @warframe_mods.error
    async def mods_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Try again in `{error.retry_after:.1f}s`.", delete_after=5)
        else:
            raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WarframeCog(bot))
