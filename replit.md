# Ordis — Warframe Discord Bot

A turn-based Warframe game implemented as a Discord bot.

## Architecture

### Bot entry point
- `bot.py` — starts the bot, loads all cogs

### Cogs (`cogs/`)
| File | Commands |
|------|----------|
| `warframe.py` | `!warframe` — roster, equip, sell, mods UI |
| `upgrades.py` | `!warframe upgrades` — full modding panel |
| `mods.py` | `!mods`, `!mods upgrade`, `!mods view` |
| `inventory.py` | `!inventory`, `!item` |
| `combat.py` | `!fight`, `!attack`, `!ability`, `!retreat` |
| `polarity.py` | `!polarity` — slot overview, mod/weapon polarity |
| `weapons.py` | `!weapons` — weapon codex |
| `shop.py` | `!shop` — credit economy |

### Data layer (`data/`)
#### JSON — single source of truth (4 domain files)
| File | Contents |
|------|----------|
| `data/mods.json` | All mod stats, costs, descriptions, TB effects, thumbnails, slot_polarities, rarity_order |
| `data/warframes.json` | Warframe base stats, mod_capacity, mod_slots, and all polarity slot arrays |
| `data/weapons.json` | Weapon stats, mod_slots per weapon, primary/secondary/melee choice lists |
| `data/enemies.json` | Enemy combat stats + drop tables + resources + cosmetics item metadata |
| `data/emojis.json` | Discord emoji ID registry (unchanged) |

#### Superseded files (no longer read by any code — safe to remove)
- `data/warframes_mods.json` ← split into `warframes.json` + `mods.json`
- `data/item_descriptions.json` ← merged into `mods.json` (mods) + `enemies.json` (resources/cosmetics)
- `data/polarities.json` ← merged into `warframes.json`, `weapons.json`, `mods.json`
- `data/drops.json` ← merged into `enemies.json` under each enemy's `"drops"` key

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
- `embeds.py` — base embed builders
- `inventory_embeds.py` — inventory display, item detail cards
- `mods_ui.py` — `!warframe mods` slot panel (Components v2)
- `polarity_embeds.py` — polarity row injectors for warframe/weapon embeds
- `weapon_embeds.py` — weapon codex embeds
- `emojis.py` — `E` class, resolves emoji names to Discord snowflakes

### Combat (`combat/`)
- `session.py` — `CombatSession` state machine
- `entities.py` — `WarframeEntity`, `EnemyEntity`
- `status.py` — status effects (Slash bleed, Knockdown, procs)

## Adding content
- **New mod**: add entry to `data/mods.json["mods"]` (dict key = mod name)
- **New warframe**: add entry to `data/warframes.json["warframes"]` + display data to `data/warframes.py::WARFRAMES`
- **New weapon**: add entry to `data/weapons.json["weapons"]` + display data to `data/weapons.py::WEAPONS`
- **New enemy**: add entry to `data/enemies.json["enemies"]` (with `drops` sub-object) — `data/enemies.py` auto-loads it
- **New drop item** (resource/cosmetic): add to `data/enemies.json["resources"]` or `["cosmetics"]`
