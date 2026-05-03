# combat/status.py
# ─────────────────────────────────────────────────────────────────────────────
# Full Warframe status-effect system adapted for turn-based combat.
#
# Physical procs:  Slash (Bleed), Puncture (Weakened), Impact (Stagger)
# Elemental procs: Heat (Ignite), Cold (Freeze), Electric (Tesla Chain), Toxin (Poison)
# Combined procs:  Blast (Detonate), Radiation (Confusion), Magnetic (Disrupt),
#                  Viral (Contagion), Corrosive (Corrosion), Gas (Gas Cloud)
# CC / field:      Knockdown, Blind, Stunned, Magnetized, Tesla Coil,
#                  Polarize Shard, Speed Buff
#
# Wiki-accurate TB adaptations (Update 36.0):
#   • Durations are in turns (1 turn ≈ 2s in real time; 6s procs = 3 turns).
#   • Abilities: 100% proc chance. Basic attacks: 20–35% proc chance.
#
# Stacking model (wiki-faithful):
#   Slash    — unlimited independent stacks (each proc is a separate bleed),
#              capped at 10 concurrent bleeds for sanity.
#   Puncture — stacks up to 5×: first stack −40% enemy dmg, each additional
#              −10% (total −80%). Also grants +5% crit chance per stack to
#              the attacker (tracked in data["crit_bonus"]).
#   Impact   — stacks up to 5×: each stack raises Mercy-kill threshold by 8%.
#   Heat     — stacks up to 10×: magnitude accumulates (50% base dmg/turn DoT).
#              ≥3 stacks causes Panic (50% chance enemy skips action).
#   Cold     — stacks up to 10×: first stack −50% enemy dmg, each additional
#              −5% (total −90% at stack 9). Stack 10 = Frozen (cannot act;
#              shields cannot regen).
#   Electric — stacks up to 10×: arc damage increases per stack.
#              First application always Stuns target for 1 turn.
#   Toxin    — stacks up to 10×: magnitude accumulates (50% base dmg/turn,
#              bypasses shields).
#   Blast    — stacks up to 5×: each stack adds delayed explosive charge
#              (30% base dmg/stack/turn). At 5 stacks → detonate all enemies.
#   Corrosive— stacks up to 10×: TEMPORARY (3 turns) — first stack −26% armor,
#              each additional −6% (total −80%). Armor fully restores on expiry.
#   Gas      — stacks up to 10×: magnitude accumulates (50% base dmg/turn AoE).
#   Magnetic — stacks up to 10×: first stack ×2.0 shield damage; each
#              additional +0.25× (max ×3.25). Nullifies shield regen.
#              On shield strip → triggers bonus Electric arc.
#   Radiation— stacks up to 5×: each additional stack extends confusion by
#              1 extra turn (first = 2t, max 7t at stack 5).
#   Viral    — stacks up to 5×: amplifies HP damage taken — first stack ×1.75,
#              each additional +0.25× (max ×2.75 at stack 5).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar


# ── Damage type → emoji map ──────────────────────────────────────────────────

DAMAGE_ICONS: dict[str, str] = {
    "slash":       "<:slash_effect:1499584690859020459>",
    "puncture":    "<:puncture:1499594734421803060>",
    "impact":      "<:impact:1499636596633374780>",
    "electricity": "<:electricity:1499596184958795917>",
    "magnetic":    "<:magnetic:1499594471770427472>",
    "blast":       "<:blast:1499594820102914210>",
    "true":        "<:true:1499594920082542743>",
    "toxin":       "☠️",
    "heat":        "🔥",
    "cold":        "❄️",
    "gas":         "🟢",
    "radiation":   "☢️",
    "viral":       "🦠",
    "corrosive":   "🧪",
    "unknown":     "<:damage:1499651176419950622>",
}

def dmg_icon(dtype: str) -> str:
    return DAMAGE_ICONS.get(dtype.lower(), DAMAGE_ICONS["unknown"])


# ── Threshold constants ───────────────────────────────────────────────────────

HEAT_PANIC_THRESHOLD     = 3   # stacks at which Heat causes 50% panic chance
COLD_FROZEN_THRESHOLD    = 10  # stacks at which Cold freezes enemy solid
BLAST_DETONATE_THRESHOLD = 5   # stacks that trigger instant AoE detonation


# ── Status types ──────────────────────────────────────────────────────────────

class StatusType(Enum):
    # ── Physical procs ───────────────────────────────────────────────────────
    SLASH_BLEED    = auto()   # Bleed DoT; 35% hit/turn × 3 turns; bypasses armor
    PUNCTURE       = auto()   # Weakened: −40% dmg (+−10%/stack) up to 5×; +5% crit/stack
    IMPACT         = auto()   # Stagger: +8% Mercy-kill threshold per stack (5× max)

    # ── Elemental procs ──────────────────────────────────────────────────────
    HEAT           = auto()   # Ignite: 50% base dmg/turn DoT + Panic at ≥3 stacks
    COLD           = auto()   # Freeze: −50% dmg (−5%/extra stack); Frozen at 10 stacks
    ELECTRIC       = auto()   # Tesla Chain: Stun on apply + arc DoT/turn (stacks 10×)
    TOXIN          = auto()   # Poison: 50% base dmg/turn; bypasses shields (10× stacks)

    # ── Combined element procs ────────────────────────────────────────────────
    BLAST          = auto()   # Detonate: charge stacks (5×); detonates for AoE at max
    RADIATION      = auto()   # Confusion: attacks allies; +1 turn per stack (5× max)
    MAGNETIC       = auto()   # Disrupt: ×2.0 shield dmg (+0.25/stack); nullifies regen
    VIRAL          = auto()   # Contagion: ×1.75 HP dmg (+0.25/stack, 5× max)
    CORROSIVE      = auto()   # Corrosion: −26% armor (−6%/stack, 10× max); TEMPORARY
    GAS            = auto()   # Gas Cloud: 50% base dmg/turn AoE (stacks 10×)

    # ── Hard crowd control ───────────────────────────────────────────────────
    KNOCKDOWN      = auto()   # Cannot act; expires at start of their next turn
    BLIND          = auto()   # Cannot act; melee Finishers deal ×8 damage
    STUNNED        = auto()   # Cannot act (Electric, Radial Javelin, Discharge)
    MAGNETIZED     = auto()   # Anchored; all damage ×2; explodes on expiry

    # ── Persistent field effects ──────────────────────────────────────────────
    TESLA_COIL     = auto()   # Arcs Electricity to all other enemies each End Phase
    POLARIZE_SHARD = auto()   # Orbiting shards deal Puncture/Slash each End Phase

    # ── Buffs ─────────────────────────────────────────────────────────────────
    SPEED_BUFF     = auto()   # +50% damage on all actions for N turns


@dataclass
class StatusEffect:
    name:        str
    status_type: StatusType
    duration:    int           # turns remaining (decremented each End Phase)
    magnitude:   float = 0.0  # damage/turn, multiplier, armor-strip %, etc.
    source:      str   = ""   # name of whoever applied this effect
    stacks:      int   = 1    # current stack count
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
        StatusType.SLASH_BLEED:    "<:slash_effect:1499584690859020459>",
        StatusType.PUNCTURE:       "<:puncture:1499594734421803060>",
        StatusType.IMPACT:         "<:impact:1499636596633374780>",
        StatusType.HEAT:           "🔥",
        StatusType.COLD:           "❄️",
        StatusType.ELECTRIC:       "<:electricity:1499596184958795917>",
        StatusType.TOXIN:          "☠️",
        StatusType.BLAST:          "<:blast:1499594820102914210>",
        StatusType.RADIATION:      "☢️",
        StatusType.MAGNETIC:       "<:magnetic:1499594471770427472>",
        StatusType.VIRAL:          "🦠",
        StatusType.CORROSIVE:      "🧪",
        StatusType.GAS:            "🟢",
        StatusType.KNOCKDOWN:      "<:stunned:1499671616479563826>",
        StatusType.BLIND:          "<:radial_blind:1499574926364119050>",
        StatusType.STUNNED:        "<:stunned:1499671616479563826>",
        StatusType.MAGNETIZED:     "<:magnetize:1499595149091668103>",
        StatusType.TESLA_COIL:     "<:electricity:1499596184958795917>",
        StatusType.POLARIZE_SHARD: "<:polarize:1499595238786994246>",
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
    """
    Bleed DoT: `magnitude` true damage/turn × 3 turns.
    Bypasses armor and shields. Unlimited stacking (up to 10 concurrent bleeds).
    Magnitude = 35% of the hit that triggered the proc.
    """
    return StatusEffect(
        name="Bleed", status_type=StatusType.SLASH_BLEED,
        duration=3, magnitude=magnitude, source=source,
    )

def make_puncture(source: str = "") -> StatusEffect:
    """
    Weakened: first stack −40% enemy damage output for 2 turns.
    Stacks up to 5×: each additional stack adds −10% (max −80%).
    Each stack also grants +5% weapon crit chance to the attacker (tracked externally).
    """
    return StatusEffect(
        name="Weakened", status_type=StatusType.PUNCTURE,
        duration=2, magnitude=0.40, source=source,
        data={"crit_bonus": 0.05},
    )

def make_impact(source: str = "") -> StatusEffect:
    """
    Stagger: staggers the target; raises Mercy-kill HP threshold by 8% per stack.
    Stacks up to 5×. Duration 1 turn.
    """
    return StatusEffect(
        name="Stagger", status_type=StatusType.IMPACT,
        duration=1, magnitude=0.08, source=source,
    )

# ── Elemental ─────────────────────────────────────────────────────────────────

def make_heat(magnitude: float, source: str = "") -> StatusEffect:
    """
    Ignite: `magnitude` Heat dmg/turn × 3 turns. Stacks up to 10× (magnitudes sum).
    ≥3 stacks causes Panic: 50% chance enemy skips its action each turn.
    Magnitude should be ~50% of the triggering hit.
    """
    return StatusEffect(
        name="Ignite", status_type=StatusType.HEAT,
        duration=3, magnitude=magnitude, source=source,
    )

def make_cold(source: str = "") -> StatusEffect:
    """
    Freeze: −50% enemy damage output first stack; each additional stack −5% more
    (total −90% at stack 9). Stack 10 = Frozen solid (cannot act; shields locked).
    Duration 3 turns. Stacks up to 10×.
    """
    return StatusEffect(
        name="Freeze", status_type=StatusType.COLD,
        duration=3, magnitude=0.50, source=source,
    )

def make_electric(arc_damage: float, source: str = "") -> StatusEffect:
    """
    Tesla Chain: stuns target for 1 turn on application. `arc_damage` arcs
    to a random other enemy each End Phase. Stacks up to 10× (arc damage scales).
    Duration 2 turns.
    """
    return StatusEffect(
        name="Tesla Chain", status_type=StatusType.ELECTRIC,
        duration=2, magnitude=arc_damage, source=source,
    )

def make_toxin(magnitude: float, source: str = "") -> StatusEffect:
    """
    Poison: `magnitude` Toxin dmg/turn × 3 turns; bypasses shields.
    Stacks up to 10× (magnitudes sum).
    Magnitude should be ~50% of the triggering hit.
    """
    return StatusEffect(
        name="Poison", status_type=StatusType.TOXIN,
        duration=3, magnitude=magnitude, source=source,
    )

# ── Combined ──────────────────────────────────────────────────────────────────

def make_blast(magnitude: float = 0.0, source: str = "") -> StatusEffect:
    """
    Detonate: plants an explosive charge on the target.
    Deals 30% of `magnitude` per stack each End Phase.
    At 5 stacks the charge detonates, dealing AoE blast damage to all enemies.
    Duration 3 turns. Stacks up to 5×.
    """
    return StatusEffect(
        name="Charge", status_type=StatusType.BLAST,
        duration=3, magnitude=magnitude, source=source,
    )

def make_radiation(source: str = "") -> StatusEffect:
    """
    Confusion: enemy attacks a random ally instead of the player.
    Duration 2 turns. Each additional stack (+1 turn, up to 5 stacks = 7 turns max).
    """
    return StatusEffect(
        name="Confusion", status_type=StatusType.RADIATION,
        duration=2, magnitude=0.0, source=source,
    )

def make_magnetic_proc(source: str = "") -> StatusEffect:
    """
    Disrupt: amplifies damage dealt to shields — first stack ×2.0 shield damage,
    each additional stack +0.25× (max ×3.25 at 10 stacks). Nullifies shield regen.
    On shield strip: triggers a bonus Electric arc (handled in session).
    Duration 3 turns. Stacks up to 10×.
    """
    return StatusEffect(
        name="Disrupt", status_type=StatusType.MAGNETIC,
        duration=3, magnitude=2.0, source=source,
    )

def make_viral(source: str = "") -> StatusEffect:
    """
    Contagion: amplifies HP damage taken — first stack ×1.75, each additional
    stack +0.25× (max ×2.75 at 5 stacks). Duration 3 turns. Stacks up to 5×.
    """
    return StatusEffect(
        name="Contagion", status_type=StatusType.VIRAL,
        duration=3, magnitude=1.75, source=source,
    )

def make_corrosive(source: str = "") -> StatusEffect:
    """
    Corrosion: strips 26% of base armor (first stack), 6% per subsequent stack
    (total 80% at 10 stacks). TEMPORARY — duration 3 turns; armor fully restores
    on expiry. Stacks up to 10×.
    """
    return StatusEffect(
        name="Corrosion", status_type=StatusType.CORROSIVE,
        duration=3, magnitude=0.26, source=source,
    )

def make_gas(magnitude: float, source: str = "") -> StatusEffect:
    """
    Gas Cloud: AoE Toxin cloud deals `magnitude` dmg/turn to ALL enemies × 3 turns.
    Stacks up to 10× (magnitudes sum). Bypasses shields (Toxin damage type).
    """
    return StatusEffect(
        name="Gas Cloud", status_type=StatusType.GAS,
        duration=3, magnitude=magnitude, source=source,
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
