# combat/status.py
# ─────────────────────────────────────────────────────────────────────────────
# Full Warframe status-effect system adapted for turn-based combat.
#
# Physical procs:  Slash, Puncture, Impact
# Elemental procs: Heat, Cold, Electric, Toxin
# Combined procs:  Blast, Radiation, Magnetic, Viral, Corrosive, Gas
# CC / field:      Knockdown, Blind, Stunned, Magnetized, Tesla Coil,
#                  Polarize Shard, Speed Buff
#
# TB adaptations:
#   • All durations are in turns, not seconds.
#   • Proc chances: guaranteed on ability hits; 20–35% on basic attacks.
#   • Stacking: same type refreshes duration if new duration is longer;
#     Heat and Toxin stack magnitude (up to 4 stacks).
#   • Corrosive: each application permanently strips 15% of the target's
#     BASE armor (max 4 stacks = 60% total strip).
#   • Viral: halves the target's effective max HP for 2 turns (debuff,
#     not actual HP loss — expires cleanly).
#   • Radiation: 25% chance target attacks a random ally instead of the
#     player for the duration.
#   • Gas: AoE Toxin cloud hits all enemies for 2 turns.
#   • Blast: guaranteed Knockdown on the hit that applies it.
#   • Cold: -30% damage on the afflicted entity's attacks for 2 turns.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar


# ── Damage type → emoji map (used everywhere in the log) ─────────────────────
# Import this dict wherever a log line needs a dynamic damage icon.

DAMAGE_ICONS: dict[str, str] = {
    # Physical
    "slash":       "<:slash_effect:1499584690859020459>",
    "puncture":    "<:puncture:1499594734421803060>",
    "impact":      "<:impact:1499636596633374780>",
    # Base elemental
    "electricity": "<:electricity:1499596184958795917>",
    "magnetic":    "<:magnetic:1499594471770427472>",
    "blast":       "<:blast:1499594820102914210>",
    # Misc / true
    "true":        "<:true:1499594920082542743>",
    "toxin":       "☠️",
    "heat":        "🔥",
    "cold":        "❄️",
    "gas":         "🟢",
    "radiation":   "☢️",
    "viral":       "🦠",
    "corrosive":   "🧪",
    # Fallback
    "unknown":     "<:damage:1499651176419950622>",
}

def dmg_icon(dtype: str) -> str:
    """Return the emoji for a given damage type string (case-insensitive)."""
    return DAMAGE_ICONS.get(dtype.lower(), DAMAGE_ICONS["unknown"])


# ── Status types ──────────────────────────────────────────────────────────────

class StatusType(Enum):
    # ── Physical procs ───────────────────────────────────────────────────────
    SLASH_BLEED    = auto()   # True DoT; 35% of hit / turn for 6 turns (TB: 2 turns)
    PUNCTURE       = auto()   # -30% damage on target's next attack (1 turn)
    IMPACT         = auto()   # -25% shield regen; soft Stagger (1 turn, cosmetic)

    # ── Elemental procs ──────────────────────────────────────────────────────
    HEAT           = auto()   # DoT + -50% armor (stacks up to 4×)
    COLD           = auto()   # -30% damage output for 2 turns
    ELECTRIC       = auto()   # Arcs to a random other enemy (chain, 1 turn)
    TOXIN          = auto()   # Bypasses shields; DoT for 2 turns (stacks up to 4×)

    # ── Combined element procs ────────────────────────────────────────────────
    BLAST          = auto()   # AoE Knockdown; -25% accuracy next turn
    RADIATION      = auto()   # Confusion: 25% chance to attack allies for 2 turns
    MAGNETIC       = auto()   # Drains 50 shields; -50% max shields for 2 turns
    VIRAL          = auto()   # Halves effective max HP for 2 turns
    CORROSIVE      = auto()   # Strips 15% base armor (stacks up to 4×, permanent)
    GAS            = auto()   # AoE Toxin cloud: hits ALL enemies for 2 turns

    # ── Hard crowd control ───────────────────────────────────────────────────
    KNOCKDOWN      = auto()   # Cannot act; expires at start of THEIR next turn
    BLIND          = auto()   # Cannot act; melee Finishers deal ×8 damage
    STUNNED        = auto()   # Cannot act; used by Discharge / Radial Javelin
    MAGNETIZED     = auto()   # Anchored; all damage ×2; explodes on expiry

    # ── Persistent field effects ──────────────────────────────────────────────
    TESLA_COIL     = auto()   # Arcs Electricity to all other enemies each End Phase
    POLARIZE_SHARD = auto()   # Orbiting shards deal Puncture/Slash each End Phase

    # ── Buffs ─────────────────────────────────────────────────────────────────
    SPEED_BUFF     = auto()   # +50% damage on actions for N turns


@dataclass
class StatusEffect:
    name:        str
    status_type: StatusType
    duration:    int           # turns remaining (decremented each End Phase)
    magnitude:   float = 0.0  # damage/turn, multiplier, armor-strip %, etc.
    source:      str   = ""   # name of whoever applied this effect
    stacks:      int   = 1    # Heat / Toxin / Corrosive can stack magnitude
    data:        dict  = field(default_factory=dict)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def tick(self) -> bool:
        """Decrement duration by 1. Returns True if still active."""
        self.duration -= 1
        return self.duration > 0

    def is_expired(self) -> bool:
        return self.duration <= 0

    # ── Display ───────────────────────────────────────────────────────────────

    ICONS: ClassVar[dict[StatusType, str]] = {
        # Physical
        StatusType.SLASH_BLEED:    "<:slash_effect:1499584690859020459>",
        StatusType.PUNCTURE:       "<:puncture:1499594734421803060>",
        StatusType.IMPACT:         "<:impact:1499636596633374780>",
        # Elemental
        StatusType.HEAT:           "🔥",
        StatusType.COLD:           "❄️",
        StatusType.ELECTRIC:       "<:electricity:1499596184958795917>",
        StatusType.TOXIN:          "☠️",
        # Combined
        StatusType.BLAST:          "<:blast:1499594820102914210>",
        StatusType.RADIATION:      "☢️",
        StatusType.MAGNETIC:       "<:magnetic:1499594471770427472>",
        StatusType.VIRAL:          "🦠",
        StatusType.CORROSIVE:      "🧪",
        StatusType.GAS:            "🟢",
        # Hard CC
        StatusType.KNOCKDOWN:      "<:stunned:1499671616479563826>",
        StatusType.BLIND:          "<:radial_blind:1499574926364119050>",
        StatusType.STUNNED:        "<:stunned:1499671616479563826>",
        StatusType.MAGNETIZED:     "<:magnetize:1499595149091668103>",
        # Field effects
        StatusType.TESLA_COIL:     "<:electricity:1499596184958795917>",
        StatusType.POLARIZE_SHARD: "<:polarize:1499595238786994246>",
        # Buffs
        StatusType.SPEED_BUFF:     "<:speed:1499596301984071832>",
    }

    def icon(self) -> str:
        return self.ICONS.get(self.status_type, "<:damage:1499651176419950622>")

    def __str__(self) -> str:
        stack_str = f"×{self.stacks}" if self.stacks > 1 else ""
        return f"{self.icon()}{self.name}{stack_str}({self.duration}t)"


# ── Factory helpers ───────────────────────────────────────────────────────────

# ── Physical ──────────────────────────────────────────────────────────────────

def make_slash_bleed(magnitude: float, source: str = "") -> StatusEffect:
    """Bleed DoT: `magnitude` true damage/turn for 2 turns. Bypasses armor & shields."""
    return StatusEffect(
        name="Bleed", status_type=StatusType.SLASH_BLEED,
        duration=2, magnitude=magnitude, source=source,
    )

def make_puncture(source: str = "") -> StatusEffect:
    """Puncture: target deals -30% damage on its next attack (1 turn)."""
    return StatusEffect(
        name="Puncture", status_type=StatusType.PUNCTURE,
        duration=1, magnitude=0.30, source=source,
    )

def make_impact(source: str = "") -> StatusEffect:
    """Impact: soft stagger — -25% shield regen for 1 turn (cosmetic CC)."""
    return StatusEffect(
        name="Impact", status_type=StatusType.IMPACT,
        duration=1, magnitude=0.25, source=source,
    )

# ── Elemental ─────────────────────────────────────────────────────────────────

def make_heat(magnitude: float, source: str = "") -> StatusEffect:
    """Heat: DoT + -50% armor while burning. Stacks magnitude up to 4×."""
    return StatusEffect(
        name="Heat", status_type=StatusType.HEAT,
        duration=2, magnitude=magnitude, source=source,
    )

def make_cold(source: str = "") -> StatusEffect:
    """Cold: -30% damage output for 2 turns."""
    return StatusEffect(
        name="Cold", status_type=StatusType.COLD,
        duration=2, magnitude=0.30, source=source,
    )

def make_electric(arc_damage: float, source: str = "") -> StatusEffect:
    """Electric: proc arcs `arc_damage` to a random adjacent enemy (1 turn)."""
    return StatusEffect(
        name="Electric", status_type=StatusType.ELECTRIC,
        duration=1, magnitude=arc_damage, source=source,
    )

def make_toxin(magnitude: float, source: str = "") -> StatusEffect:
    """Toxin: bypasses shields; DoT for 2 turns. Stacks magnitude up to 4×."""
    return StatusEffect(
        name="Toxin", status_type=StatusType.TOXIN,
        duration=2, magnitude=magnitude, source=source,
    )

# ── Combined ──────────────────────────────────────────────────────────────────

def make_blast(source: str = "") -> StatusEffect:
    """Blast: guaranteed Knockdown + -25% accuracy next turn (1 turn)."""
    return StatusEffect(
        name="Blast", status_type=StatusType.BLAST,
        duration=1, source=source,
    )

def make_radiation(source: str = "") -> StatusEffect:
    """Radiation: 25% chance to attack an ally instead of the player for 2 turns."""
    return StatusEffect(
        name="Radiation", status_type=StatusType.RADIATION,
        duration=2, magnitude=0.25, source=source,
    )

def make_magnetic_proc(source: str = "") -> StatusEffect:
    """Magnetic: drain 50 shields; -50% max shields for 2 turns."""
    return StatusEffect(
        name="Magnetic", status_type=StatusType.MAGNETIC,
        duration=2, magnitude=0.50, source=source,
    )

def make_viral(source: str = "") -> StatusEffect:
    """Viral: halves effective max HP for 2 turns (damage ignores upper half)."""
    return StatusEffect(
        name="Viral", status_type=StatusType.VIRAL,
        duration=2, magnitude=0.50, source=source,
    )

def make_corrosive(armor_strip_pct: float = 0.15, source: str = "") -> StatusEffect:
    """Corrosive: permanently strips `armor_strip_pct` of base armor (max 4 stacks)."""
    return StatusEffect(
        name="Corrosive", status_type=StatusType.CORROSIVE,
        duration=999, magnitude=armor_strip_pct, source=source,
    )

def make_gas(magnitude: float, source: str = "") -> StatusEffect:
    """Gas: AoE Toxin cloud damages ALL enemies for 2 turns."""
    return StatusEffect(
        name="Gas Cloud", status_type=StatusType.GAS,
        duration=2, magnitude=magnitude, source=source,
    )

# ── Hard CC ───────────────────────────────────────────────────────────────────

def make_knockdown(source: str = "") -> StatusEffect:
    """Knockdown: skip next turn."""
    return StatusEffect(
        name="Knockdown", status_type=StatusType.KNOCKDOWN,
        duration=1, source=source,
    )

def make_blind(duration: int = 2, source: str = "") -> StatusEffect:
    """Blind: cannot act; Finishers deal ×8 damage."""
    return StatusEffect(
        name="Blind", status_type=StatusType.BLIND,
        duration=duration, source=source,
    )

def make_stunned(duration: int = 1, source: str = "") -> StatusEffect:
    """Stun: cannot act for N turns."""
    return StatusEffect(
        name="Stunned", status_type=StatusType.STUNNED,
        duration=duration, source=source,
    )

def make_magnetized(duration: int = 3, source: str = "") -> StatusEffect:
    """Magnetize: anchor + ×2 damage multiplier + explodes on expiry."""
    return StatusEffect(
        name="Magnetized", status_type=StatusType.MAGNETIZED,
        duration=duration, magnitude=2.0, source=source,
    )

# ── Field effects ─────────────────────────────────────────────────────────────

def make_tesla_coil(arc_damage: float, duration: int = 2, source: str = "") -> StatusEffect:
    """Tesla Coil: arcs `arc_damage` Electricity to all other enemies each End Phase."""
    return StatusEffect(
        name="Tesla Coil", status_type=StatusType.TESLA_COIL,
        duration=duration, magnitude=arc_damage, source=source,
    )

def make_polarize_shard(damage_per_turn: float = 20.0, duration: int = 3, source: str = "") -> StatusEffect:
    """Polarize Shard: deals Puncture/Slash to all enemies each End Phase."""
    return StatusEffect(
        name="Polarize Shard", status_type=StatusType.POLARIZE_SHARD,
        duration=duration, magnitude=damage_per_turn, source=source,
    )

# ── Buffs ─────────────────────────────────────────────────────────────────────

def make_speed_buff(duration: int = 2, source: str = "") -> StatusEffect:
    """Speed: +50% damage on all actions for N turns."""
    return StatusEffect(
        name="Speed", status_type=StatusType.SPEED_BUFF,
        duration=duration, magnitude=0.5, source=source,
    )
