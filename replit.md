# Ordis — Warframe Discord Bot

A turn-based Warframe game implemented as a Discord bot.

## Architecture

### Bot entry point
- `bot.py` — starts the bot, loads all cogs; includes a global `@bot.check` that blocks every command except `!warframe` for uninitialized players

### Cogs (`cogs/`)
| File | Commands | Notes |
|------|----------|-------|
| `warframe.py` | `!warframe` — roster, equip, sell, mods UI | Also drives tutorial step resume |
| `weapon.py` | weapon select (tutorial step 2) | Sets `tutorial_step = secondary_select` |
| `secondary.py` | secondary select (tutorial step 3) | Sets `tutorial_step = melee_select` |
| `melee.py` | melee select (tutorial step 4 → launches combat) | Detects tutorial; creates restricted `CombatSession` |
| `combat.py` | `!fight`, `!attack`, `!ability`, `!retreat` | Handles `_finish_tutorial` on tutorial session end |
| `quests.py` | `!quests` / `!quest start <id>` | Quest Log; reads from `data/quests/*.json` |
| `upgrades.py` | `!warframe upgrades` — full modding panel | |
| `mods.py` | `!mods`, `!mods upgrade`, `!mods view` | |
| `inventory.py` | `!inventory`, `!item` | |
| `polarity.py` | `!polarity` — slot overview, mod/weapon polarity | |

### Tutorial + Quest flow

**5-step tutorial** (all uninitialized players must complete before other commands unlock):

| Step | `tutorial_step` value | What happens |
|------|-----------------------|-------------|
| 1 | `None` (first visit) | `!warframe` → TutorialWarframeView |
| 2 | `primary_select` | TutorialChooseButton → WeaponView |
| 3 | `secondary_select` | ChooseWeaponButton → SecondaryView |
| 4 | `melee_select` | ChooseSecondaryButton → MeleeView |
| 5 | `awakening_mission` | ChooseMeleeButton → restricted CombatSession (`tutorial=True`) |

On Awakening victory: `initialized = True`, `current_quest = "vors_prize"`, `current_mission = "tolstoj"`.  
On Awakening defeat: player stays uninitialized, `tutorial_step = "awakening_mission"` — must use `!warframe` to try again.

`!warframe` re-invocation resumes from the saved `tutorial_step` (no restart needed).

**Tutorial CombatSession restrictions** (`tutorial=True`):
- `profile=None` → no mod bonuses applied
- `AbilityButton` and `HoldCastButton` are disabled
- `_collect_drops()` returns early → no loot, no credits

**Command guard** (`bot.py`):
- `@bot.check` on every command
- Only `!warframe` (and subcommands) is allowed while `initialized == False`
- All other commands, including `!quests`, return a tutorial-redirect message

### Quest system

Quest data: `data/quests/<quest_id>.json`  
Player state: `current_quest`, `current_mission`, `completed_quests` in player profile

**Vor's Prize** (`data/quests/vors_prize.json`):
- Arc 1 → Awakening (tutorial mission, auto-completed via `_finish_tutorial`)
- Arc 2 → Tolstoj on Mercury (first regular post-tutorial mission)

`!quests` / `!quest` — show active quest, completed quests, available quests  
`!quest start <id>` — start a named quest (when no current quest)

### Data layer (`data/`)
#### JSON — single source of truth (4 domain files + quests)
| File | Contents |
|------|----------|
| `data/mods.json` | All mod stats, costs, descriptions, TB effects, thumbnails, slot_polarities, rarity_order |
| `data/warframes.json` | Warframe base stats, mod_capacity, mod_slots, and all polarity slot arrays |
| `data/weapons.json` | Weapon stats, mod_slots per weapon, primary/secondary/melee choice lists |
| `data/enemies.json` | Enemy combat stats + drop tables + resources + cosmetics item metadata |
| `data/emojis.json` | Discord emoji ID registry |
| `data/quests/*.json` | Quest definitions: arcs, missions, enemies, dialogue, rewards |

#### Player profile schema (v6 + tutorial fields)
New fields added (all migrate safely via `setdefault`):
- `tutorial_step` — `None | "primary_select" | "secondary_select" | "melee_select" | "awakening_mission"`
- `current_quest` — active quest ID string or `None`
- `current_mission` — active mission ID string or `None`
- `completed_quests` — list of completed quest ID strings

#### Python loaders
| File | Role |
|------|------|
| `data/enemies.py` | Loads `enemies.json`, hydrates `icon` emojis via `E.xxx`, exports `ENEMIES` + `INTRO_ENCOUNTER` |
| `data/weapons.py` | Defines `WEAPONS` display dict with emoji formatting; loads slot data from `weapons.json` via `polarity.py` |
| `data/warframes.py` | Defines `WARFRAMES` display dict with ability formatting; structural data lives in `warframes.json` |
| `data/polarity.py` | Loads slot polarities from `warframes.json`, `weapons.json`, `mods.json`; exposes helper functions |
| `data/drops.py` | Loads enemy drop tables from `enemies.json`; exposes `roll_drops()` |
| `data/persistence.py` | Player profile CRUD (`./data/players/`), mod instance factory, global state |

### Utils (`utils/`)
- `embeds.py` — base embed builders (Warframe selector, tutorial entry)
- `inventory_embeds.py` — inventory display, item detail cards
- `mods_ui.py` — `!warframe mods` slot panel (Components v2)
- `polarity_embeds.py` — polarity row injectors for warframe/weapon embeds
- `weapon_embeds.py` — weapon codex embeds
- `combat_embeds.py` — live combat + post-mission loot embeds
- `emojis.py` — `E` class, resolves emoji names to Discord snowflakes

### Combat (`combat/`)
- `session.py` — `CombatSession` state machine; `tutorial: bool` flag skips mod bonuses and loot
- `entities.py` — `WarframeEntity`, `EnemyEntity`
- `status.py` — status effects (Slash bleed, Knockdown, procs)
- `abilities.py` — per-warframe ability implementations
- `weapons.py` — weapon stat registry

## Adding content
- **New mod**: add entry to `data/mods.json["mods"]` (dict key = mod name)
- **New warframe**: add entry to `data/warframes.json["warframes"]` + display data to `data/warframes.py::WARFRAMES`
- **New weapon**: add entry to `data/weapons.json["weapons"]` + display data to `data/weapons.py::WEAPONS`
- **New enemy**: add entry to `data/enemies.json["enemies"]` (with `drops` sub-object) — `data/enemies.py` auto-loads it
- **New drop item** (resource/cosmetic): add to `data/enemies.json["resources"]` or `["cosmetics"]`
- **New quest**: create `data/quests/<quest_id>.json` following the `vors_prize.json` schema
