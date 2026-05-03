# Warframe Wiki Mods Extraction Prompt

## Objective
Extract **complete, wiki-verified stats** for all Warframe mods from https://wiki.warframe.com. The output is a JSON database compatible with Turn-Based combat mechanics.

---

## Data Collection Strategy

### Phase 1: Index All Mods by Category
Fetch the following category pages and list every mod:

1. **Warframe Mods**: https://wiki.warframe.com/w/Category:Warframe_Mods
   - Filter: Common, Uncommon, Rare
   - Expected: ~30–40 mods (Vitality, Redirection, Steel Fiber, Flow, Streamline, Continuity, etc.)

2. **Rifle Mods**: https://wiki.warframe.com/w/Category:Rifle_Mods
   - Expected: ~20–30 mods (Serration, Point Strike, Split Chamber, North Wind, etc.)

3. **Shotgun Mods**: https://wiki.warframe.com/w/Category:Shotgun_Mods
   - Expected: ~10–15 mods

4. **Pistol/Secondary Mods**: https://wiki.warframe.com/w/Category:Secondary_Mods
   - Expected: ~20–30 mods (Hornet Strike, Barrel Diffusion, etc.)

5. **Melee Mods**: https://wiki.warframe.com/w/Category:Melee_Mods
   - Expected: ~25–35 mods (Pressure Point, Heavy Trauma, Rending Strike, etc.)

6. **Stance Mods**: https://wiki.warframe.com/w/Category:Stance_Mods
   - Expected: ~15–20 mods (Iron Phoenix, Tranquil Cleave, etc.)

---

## Data Extraction per Mod

For each mod, visit its wiki page (e.g., https://wiki.warframe.com/w/Vitality) and extract:

### Basic Info
- **Mod Name** (exact spelling from wiki)
- **Category** (Warframe, Rifle, Shotgun, Pistol, Melee, Stance)
- **Rarity** (Common, Uncommon, Rare)
- **Polarity** (Madurai ◆, Naramon ◉, Vazarin ◐, etc.; "any" if none)
- **Description** (full wiki description, first 2–3 sentences)

### Rank & Drain Info
Extract the **Rank table** from the wiki page (copy the stat table):

| Rank | Effect | Cost |
|------|--------|------|
| 0    | +9%    | 2    |
| ...  | ...    | ...  |
| 10   | +100%  | 12   |

From this table, extract:
- **max_rank** (highest rank number)
- **base_drain** (Cost at Rank 0)
- **max_drain** (Cost at max_rank)
- **endo_costs_per_rank** array: [cost_R0, cost_R1, ..., cost_R_max]
- **credit_costs_per_rank** array: Calculate using formula:
  - **Common**: base_cost = 483, multiply by 2^(rank-1)
    - R0=483, R1=966, R2=1932, R3=3864, ..., R10=494592
  - **Uncommon**: base_cost = 966
  - **Rare**: base_cost = 1449

### Stat Scaling
From the Rank table, extract **per_rank scaling**:

Example (Vitality R0=+9%, R10=+100%):
- per_rank = (100 – 9) / 10 ≈ 9–10% per rank
- Store as: `"rank_scaling": {"health_percent": {"per_rank": 10}}`

For multi-stat mods (e.g., Rending Strike: Slash + Puncture):
```json
"rank_scaling": {
  "slash_damage_percent":    {"per_rank": 20},
  "puncture_damage_percent": {"per_rank": 27}
}
```

### Max Stats Calculation
Multiply per_rank × max_rank:

Example (Vitality, per_rank=10, max_rank=10):
- `stats: {"health_percent": 100}`

---

## Critical Verification Checklist

Before adding a mod to the database, **verify ALL of these**:

1. ✅ **Rank table matches wiki exactly** — Copy the wiki table as-is, verify all rows
2. ✅ **Max rank is correct** (not off-by-one errors)
   - Vitality: R0–R10 = **11 ranks, max_rank=10** ✓
   - Flow: R0–R5 = **6 ranks, max_rank=5** ✓
3. ✅ **Drain costs are correct** for the rarity
   - Common mods start at drain 2–4, max 6–14
   - Rare mods often start at drain 4–10
4. ✅ **Rarity matches wiki** — Don't assume; read the "Rarity" row
   - Flow is **Rare**, not Uncommon ✓
   - Serration is **Uncommon**, not Common ✓
5. ✅ **Per-rank math checks out**
   - (max_effect – base_effect) / max_rank ≈ per_rank
   - Vitality: (100% – 9%) / 10 = 9.1% ≈ 10/rank ✓
6. ✅ **No duplication** — Each mod name appears once
7. ✅ **Weapon compatibility filled** — Which weapons can equip this mod

---

## Output Format

### JSON Schema

```json
{
  "mods": {
    "Vitality": {
      "uuid": "CDX-VIT-001",
      "name": "Vitality",
      "category": "Warframe",
      "rarity": "common",
      "polarity": "madurai",
      "base_drain": 2,
      "max_drain": 12,
      "max_rank": 10,
      "stats": {
        "health_percent": 100
      },
      "rank_scaling": {
        "health_percent": {
          "per_rank": 10
        }
      },
      "description": "Increases the Warframe's maximum Health...",
      "base_effect": "+9% Health",
      "max_effect": "+100% Health",
      "endo_costs_per_rank": [10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120],
      "credit_costs_per_rank": [483, 966, 1932, 3864, 7728, 15456, 30912, 61824, 123648, 247296],
      "tb_effect": "Multiplies your Warframe's base HP by the listed percentage...",
      "thumbnail": "<URL or null>",
      "compatible_weapons": [],
      "stance_weapon": null,
      "weapon_class": null
    },
    "Serration": {
      "uuid": "CDX-SER-010",
      "name": "Serration",
      "category": "Rifle",
      "rarity": "uncommon",
      "polarity": "madurai",
      "base_drain": 4,
      "max_drain": 14,
      "max_rank": 10,
      "stats": {
        "rifle_damage_percent": 165
      },
      "rank_scaling": {
        "rifle_damage_percent": {
          "per_rank": 15
        }
      },
      "description": "Serrated rounds tear through targets...",
      "base_effect": "+15% Rifle Damage",
      "max_effect": "+165% Rifle Damage",
      "endo_costs_per_rank": [20, 40, 80, 160, 320, 640, 1280, 2560, 5120, 10240],
      "credit_costs_per_rank": [966, 1932, 3864, 7728, 15456, 30912, 61824, 123648, 247296, 494592],
      "tb_effect": "Multiplies the total damage of your equipped Primary rifle...",
      "thumbnail": null,
      "compatible_weapons": ["MK1-Braton"],
      "stance_weapon": null,
      "weapon_class": "Primary"
    }
  },
  "slot_polarities": {
    "warframe_0": "madurai",
    "warframe_1": "vazarin",
    "..."
  },
  "rarity_order": ["rare", "uncommon", "common"]
}
```

---

## Stat Key Naming Convention

Use these snake_case keys for all stats:

### Warframe Stats
- `health_percent`
- `shields_percent`
- `armor_percent`
- `energy_percent`
- `ability_efficiency_percent` (drain reduction)
- `ability_duration_percent`
- `ability_strength_percent`
- `ability_range_percent`
- `knockdown_chance_percent`
- `loot_bonus_percent`
- `puncture_resist_percent`
- `electricity_store_percent`

### Weapon Stats
- `rifle_damage_percent` / `pistol_damage_percent` / `melee_damage_percent`
- `crit_chance_percent`
- `multishot_percent`
- `status_chance_percent`
- `ammo_max_percent`
- `reload_speed_percent`
- `ammo_conversion_ratio`

### Elemental Damage Stats
- `cold_damage_percent`
- `heat_damage_percent`
- `electricity_damage_percent`
- `toxin_damage_percent`
- `impact_damage_percent`
- `slash_damage_percent`
- `puncture_damage_percent`

### Special Stats
- `slash_proc_duration_percent`
- `heavy_attack_efficiency_percent`
- `combo_efficiency_percent`

---

## Special Cases

### 1. Stance Mods (max_rank = 0)
Stance mods don't rank up in-game. Set:
```json
{
  "max_rank": 0,
  "stats": {},
  "rank_scaling": {},
  "endo_costs_per_rank": [],
  "credit_costs_per_rank": [],
  "base_effect": "Unlocks [Stance Name] combo tree",
  "max_effect": "Unlocks [Stance Name] combo tree"
}
```

### 2. Multi-Stat Mods (e.g., Rending Strike: Slash + Puncture)
```json
{
  "stats": {
    "slash_damage_percent": 60,
    "puncture_damage_percent": 80
  },
  "rank_scaling": {
    "slash_damage_percent": {"per_rank": 20},
    "puncture_damage_percent": {"per_rank": 27}
  }
}
```

### 3. Mods with Non-Linear Scaling
If a mod's per-rank values vary (e.g., Flow: R0=+17%, R5=+100%):
- Calculate per_rank as average: (100 – 17) / 5 = 16.6 ≈ **17** per_rank
- Verify: 17 × 6 ≈ 102% ✓ (within rounding error)

---

## Sources & References

- **Primary**: https://wiki.warframe.com
- **Backup**: https://overframe.gg (crosscheck stats)
- **Turn-Based Adaptation**: https://warframe.fandom.com (for ability synergies)

---

## Delivery Checklist

Before finalizing the mods.json:

- [ ] All 8+ mod categories indexed
- [ ] 100+ mods extracted (warframe, rifle, shotgun, pistol, melee, stance)
- [ ] All rank tables verified against wiki
- [ ] All drain costs calculated correctly
- [ ] All per_rank values match wiki math
- [ ] Max stats = per_rank × max_rank
- [ ] No duplicates (case-insensitive name check)
- [ ] All stat keys use snake_case
- [ ] All required fields populated (uuid, name, category, rarity, polarity, base_drain, max_drain, max_rank, stats, rank_scaling, etc.)
- [ ] Endo/credit cost arrays match max_rank length
- [ ] Turn-Based effect descriptions filled in for each mod
- [ ] JSON parses without errors
- [ ] File passes validation: no mod with empty rank_scaling when max_rank > 0

---

## Example Workflow

1. Open https://wiki.warframe.com/w/Vitality
2. Copy the Rank table (all rows R0–R10)
3. Extract: max_rank=10, base_drain=2, max_drain=12
4. Calculate: per_rank=(100-9)/10=9.1≈10, stats=100
5. Generate endo_costs: [10, 20, 40, ..., 5120]
6. Generate credit_costs: [483, 966, 1932, ..., 247296]
7. Fill description, base_effect, max_effect, tb_effect
8. Add UUID (CDX-VIT-001), polarity (madurai), rarity (common)
9. Verify all fields non-empty
10. Move to next mod

Repeat for 100+ mods.

---

**Total Estimated Mods**: 110–150 across all categories  
**Expected JSON size**: ~500–700 KB (5,000–10,000 lines)
