# Foundry Recipes Expansion Prompt

Use this prompt to continue expanding `data/foundry_recipes.json` in future sessions.

---

## TASK

Expand `data/foundry_recipes.json` with **full, wiki-verified** crafting recipes for every craftable item in Warframe. Source: **warframe.fandom.com** only. No approximations, no training-data guesses.

## RULES

1. **Skip** any entry where `wiki_verified: true` already exists — do not re-fetch or overwrite it.
2. **Fetch live** from the wiki for every new/unverified entry. Use `webFetch({url})` in code_execution.
3. **Parse** using the two stored parsers:
   - `globalThis.parseWikiRecipes(md)` — warframe pages (Base64 images, multi-table)
   - `globalThis.parseRawTable(md)` — weapon/sentinel/resource pages (inline URLs)
4. If a parser returns empty results, print the raw `Time:` context slice and extract manually.
5. **base_time convention**: ≤12h = 300, ≤24h = 480, >24h = 720.
6. **Do not add** items with no `Time:` on their wiki page — they are not foundry-craftable.

## CATEGORIES TO COVER (in priority order)

| Category | Key in JSON | wiki_source pattern |
|---|---|---|
| Craftable resources | `craftable_resource` | `/wiki/Forma`, `/wiki/Orokin_Catalyst`, etc. |
| Warframe main BPs | `warframe` | `/wiki/<FrameName>` |
| Warframe components | `warframe_part` | parsed from same frame page |
| Primary weapons | `primary` | `/wiki/<WeaponName>` |
| Secondary weapons | `secondary` | `/wiki/<WeaponName>` |
| Melee weapons | `melee` | `/wiki/<WeaponName>` |
| Sentinels | `sentinel` | `/wiki/<SentinelName>` |
| Sentinel weapons | `sentinel_weapon` | `/wiki/<WeaponName>` |
| Archwing | `archwing` | `/wiki/<ArchwingName>` |
| Archwing weapons | `archwing_weapon` | `/wiki/<WeaponName>` |
| K-Drive | `kdrive` | `/wiki/<KDriveName>` |

## WORKFLOW

```
1. Read current DB:
   const db = JSON.parse(fs.readFileSync('data/foundry_recipes.json','utf8'));

2. Find items already verified:
   const verified = new Set(Object.keys(db.items).filter(k => db.items[k].wiki_verified));

3. Build target list (items NOT in verified set), fetch ALL in parallel:
   const results = await Promise.all(targets.map(async ([name,url]) => { ... }));

4. Parse each page → extract {credits, base_time, ingredients}

5. Add to db.items with structure:
   {
     name, type, category, wiki_verified: true,
     wiki_source: "warframe.fandom.com/wiki/...",
     ingredients: { "Resource Name": amount, ... },
     credit_cost, base_time,
     result_key, result_name, result_type
   }

6. Update db._meta.version, entry_count, last_updated

7. fs.writeFileSync('data/foundry_recipes.json', JSON.stringify(db, null, 2))
```

## CURRENT STATE (as of v6.0 — 2026-05-03)

- **363 total entries, 363/363 wiki_verified**
- 59 warframes × 4 entries each = 236 entries
- 33 primaries, 19 secondaries, 55 melee, 9 sentinels, 6 craftable resources

## KNOWN GAPS TO FILL NEXT

### Primaries
- Cernos, Boar, Sobek, Baza, Castanas, Quartakk
- Archwing primaries: Fluctus, Imperator, Phaedra, Grattler

### Secondaries  
- Acrid, Embolist, Spectra, Stug, Atomos, Twin Vipers
- Catchmoon (Kitgun — skip, modular), Rattleguts (skip)

### Melee
- Paracesis, Xoris, Quassus, Pulmonars, Trumna (check craftability)

### Sentinels
- Carrier (already in DB — verify)
- Sentinel weapons: not craftable (come with sentinel purchase)

### Craftable Resources
- Exilus Adapter, Aura Forma, Umbra Forma, Nitain Extract (via Nightwave — skip?)
- Pathos Clamp, Lua Thrax Plasm, Entrati Lanthorn (bounty drops — skip, not foundry crafted)

### Archwing (entire category missing)
- Amesha, Itzal, Elytron, Odonata
- Archwing weapons: Fluctus, Imperator Vandal, Phaedra, Grattler, etc.

## KEY FILES

- `data/foundry_recipes.json` — main DB
- `cogs/foundry.py` — foundry cog that reads this DB
- `docs/foundry_expansion_prompt.md` — this file

## PARSERS (re-declare if globalThis is lost)

```javascript
// Warframe page parser (handles Base64 images in crafting tables)
function parseWikiRecipes(md) { /* ... see cogs/foundry.py or previous sessions */ }

// Weapon/sentinel/resource page parser (handles inline URL images)
function parseRawTable(md) {
  const rows = [];
  for (const rawLine of md.split('\n')) {
    const line = rawLine.trim();
    if (!line.startsWith('|') || !line.toLowerCase().includes('time:')) continue;
    const cells = line.split('|').map(c=>c.trim()).filter(c=>c.length>0);
    let base_time=480, credits=0;
    const tm = line.match(/time:\s*(\d+(?:\.\d+)?)\s*(day|hour|hr)/i);
    if (tm) { const h=tm[2].toLowerCase().startsWith('day')?+tm[1]*24:+tm[1];
      base_time=h<=12?300:h<=24?480:720; }
    const ingredients={};
    for (const cell of cells) {
      if (cell.toLowerCase().includes('time:')) continue;
      const bp=cell.split('<br>');
      if (bp.length<2) continue;
      const amt=parseInt(bp[bp.length-1].replace(/,/g,''));
      if (isNaN(amt)||amt<=0) continue;
      const links=[...bp[0].matchAll(/\[([^\]]+)\]\([^)]*\)/g)]
        .map(m=>m[1]).filter(l=>!l.startsWith('!')&&!l.startsWith('http'));
      const name=links[links.length-1]?.trim()||'';
      if (!name) continue;
      if (name==='Credits'){credits=amt;continue;}
      ingredients[name]=amt;
    }
    if (Object.keys(ingredients).length>0||credits>0) rows.push({credits,base_time,ingredients});
  }
  return rows;
}
```
