# Warframe Mod Research & Verification Guide

## System Information

### Mod System Architecture
- **Supported Stat Keys for Combat:**
  - `health_percent` → Final calculation: base_health * (1 + bonus/100)
  - `shields_percent` → Final calculation: base_shields * (1 + bonus/100)
  - `armor_percent` → Final calculation: base_armor * (1 + bonus/100)
  - `energy_percent` → Final calculation: base_energy * (1 + bonus/100)
  - `ability_efficiency_percent` → Reduces ability energy costs by this percentage
  - `puncture_resist_percent` → Reduces puncture proc damage
  - `knockdown_chance_percent` → Chance to cause knockdown on hit
  - `loot_bonus_percent` → Increases mission loot rarity/quantity
  - `electricity_store_percent` → Stores electricity proc for later use

### Rank Scaling Formula
```
stat_at_rank = ceil(per_rank * effective_rank)
effective_rank = max(1, rank)  # Rank 0 applies rank-1 base effect
```

Example: Vitality with per_rank=10
- Rank 0: 10% × 1 = 10% (displays as +9% rounded)
- Rank 5: 10% × 5 = 50%
- Rank 10: 10% × 10 = 100%

### Turn-Based Combat Considerations

1. **Health/Shields/Armor** — Direct multiplicative bonuses to survivability
2. **Energy** — More energy = more ability casts per turn
3. **Ability Efficiency** — Critical for turn economy (fewer turns to recharge)
4. **Status Resistance** — Reduces debuff effectiveness
5. **Knockdown Chance** — Enemy control in combat
6. **Loot Bonus** — Mission rewards scaling

## Current Implementation Status

**Total Mods:** 101
**Categories Present:**
- Warframe mods (survivability, ability mods)
- Primary weapon mods (rifle damage, crit, etc.)
- Secondary weapon mods (pistol damage)
- Melee weapon mods (damage, crit, attack speed)
- Companion mods (if applicable)
- Stance mods (melee stances)

## Top Priority Mods (Verified in System)

### Warframe Survivability
- ✅ **Vitality** — +100% Health (max) | Madurai | Common
- ✅ **Redirection** — +100% Shields (max) | Vazarin | Common
- ✅ **Steel Fiber** — +100% Armor (max) | Naramon | Common

### Energy & Ability Mods
- ✅ **Flow** — +100% Energy (max) | Naramon | RARE
- ✅ **Streamline** — +30% Ability Efficiency (max) | Naramon | RARE
- ✅ **Continuity** — +30% Ability Duration (max) | Naramon | RARE
- ✅ **Constitution** — +40% Ability Duration (max) | Penjaga | RARE

### Weapon Damage
- ✅ **Serration** — +165% Primary weapon damage (max) | Madurai | RARE
- ✅ **Hornet Strike** — +220% Secondary weapon damage (max) | Madurai | RARE
- ✅ **Pressure Point** — +165% Melee damage (max) | Madurai | RARE

### Weapon Crit & Status
- ✅ **Point Strike** — +150% Crit chance (max) | [Check polarity]
- ✅ **Organ Shatter** — +150% Crit damage (max) | [Check polarity]
- ✅ **Heavy Impact** — +60% Impact proc damage (max)
- ✅ **True Steel** — +80% Melee crit chance (max)

### Attack Speed & Combo
- ✅ **Rush** — +40% Attack speed (max)
- ✅ **Body Count** — +60% Combo duration (max)
- ✅ **Life Strike** — Heals on hit (life steal mechanics)

## Data Verification Checklist

For each mod, verify:
- [ ] **UUID** format: `PREFIX-CODE-###` (3-letter prefix, 3-digit code)
- [ ] **Name** matches wiki exactly
- [ ] **Category** is one of: Warframe, Primary, Secondary, Melee, Companion
- [ ] **Rarity** is one of: common, uncommon, rare
- [ ] **Polarity** is valid (madurai, naramon, vazarin, zenurik, unairu, penjaga, koneksi, umbra, any)
- [ ] **Base drain** ≤ **Max drain**
- [ ] **Max rank** is correct (5 for rare, 10 for uncommon/common)
- [ ] **Rank scaling** matches wiki formula
- [ ] **Base effect** = per_rank × 1 (approximately)
- [ ] **Max effect** = per_rank × max_rank
- [ ] **Endo costs** follow exponential pattern (2^(rank-1) × base)
- [ ] **Credit costs** follow consistent multiplier
- [ ] **TB effect** clearly explains turn-based impact
- [ ] **Thumbnail** URL is valid (Discord CDN)

## Wiki Reference URLs

- **Base Mod List:** https://wiki.warframe.com/w/Mod/List_of_Mods
- **Mod Data Module:** https://wiki.warframe.com/w/Module:Mods/data
- **Individual Mod:** https://wiki.warframe.com/w/[ModName]

**Pattern:** Replace `[ModName]` with underscored name (e.g., `/w/Pressure_Point`)

## Missing/Needs Verification

Research and verify on wiki, then add to mods.json if missing:

### Additional Warframe Mods to Consider
- Augur Mods (if available)
- Event-specific mods
- Prime variants (if tracked separately)

### Weapon Damage Mod Types
- Electricity, Heat, Cold, Toxin (status damage types)
- Multishot, Accuracy, Magazine size modifiers
- Element combinations (magnetic, radiation, corrosive, etc.)

### Combo/Status System Mods
- Bleeding/bleed procs (Slash madurai)
- Puncture procs (armor reduction)
- Impact procs (stun chance)
- Status chance modifiers
- Status duration modifiers

## Emoji Coverage in emojis.json

Current gaps that need placeholder or real emoji:
- Damage types: slash, puncture, impact, electricity, heat, cold, toxin, magnetic, radiation, viral, corrosive, blast, gas
- Enemy types: Most have ❔ placeholder
- Warframe abilities: Many have emoji, some missing
- Items/resources: Many have emoji, some need updates

## Next Steps

1. ✅ Analyze current 101 mods structure
2. ✅ Document rank scaling formulas
3. ⏳ Fact-check top 20 core mods against live wiki
4. ⏳ Verify TB effect descriptions for accuracy
5. ⏳ Add missing mods from wiki (if any critical ones)
6. ⏳ Update emoji values in emojis.json
7. ⏳ Test mod bonuses in combat session

## How to Add a New Mod

1. Choose a UUID: `CDX-ABC-###` (use next available)
2. Verify stats on wiki (base effect, max effect, max rank, drain)
3. Calculate rank_scaling.per_rank = (max_effect - base_effect) / (max_rank - 1)
4. Calculate endo_costs per rank: base_endo = 10/20/30 (common/uncommon/rare)
5. Calculate credits: credits = base_endo × 50-ish (consistent multiplier)
6. Write TB effect description focusing on combat impact
7. Get thumbnail URL from item_cdn.txt or Discord CDN
8. Add to mods.json under appropriate category
9. Add emoji key to emojis.json if needed

## Example Mod Entry

```json
"Vitality": {
  "_wiki": "https://wiki.warframe.com/w/Vitality",
  "_wiki_note": "Max rank 10. R0=+9%…R10=+100%. Drain: 2→12. Common, Madurai.",
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
  "description": "Increases Warframe Health by percentage.",
  "base_effect": "+9% Health",
  "max_effect": "+100% Health",
  "endo_costs_per_rank": [10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120],
  "credit_costs_per_rank": [483, 966, 1932, 3864, 7728, 15456, 30912, 61824, 123648, 247296],
  "tb_effect": "At rank 0, adds 10% HP. At max rank, multiplies HP by 2x.",
  "thumbnail": "https://...",
  "compatible_weapons": [],
  "stance_weapon": null,
  "weapon_class": null
}
```
