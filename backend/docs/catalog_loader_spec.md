# Catalog Loader Spec — DB → `Product` (clean-room, no `catalog.json`)

**Goal.** The product DB table is the single source of raw data. A **loader** reads rows and emits
validated `Product` objects for the layout engine. There is no JSON catalog. This one document
replaces three things that exist today: the `build_catalog_extended.py` importer, the runtime
`backfill_product`, and `CatalogRepository.load` — all of their logic collapses into the loader.

The loader has exactly one job: **for each DB row → filter, normalize, map/derive, validate → keep or
drop (with a logged reason).**

---

## 1. Source — the product table (raw columns, already present)

The CSV export is a column dump of this table, so these columns exist. The loader **reads** only the
left group; the right group is stored but never read by the engine.

| Read by the loader | Ignored by the engine |
|---|---|
| `id`, `name_english`, `category`, `price_amount`, `width`, `length`, `height`, `dimension_unit`, `two_d_icon`, `image_url`, `main_color`, `secondary_colors`, `product_color`, `styles`, `store_id` (or icon path) | `uuid`, `price_unit`, `product_url`, `is_active`, `pinecone_id`, `file_id`, `time_created`, `time_updated`, `detection`, `three_d_model`, `name_arabic` |

> `is_active` may be used as a **SQL-side pre-filter** (`WHERE is_active`), but the engine never reads it.

---

## 2. Target — the `Product` object (the only shape the engine accepts)

`Product` is a **strict** model (`extra="forbid"`): the row projection must contain **exactly** these
keys — no extras, no omissions of required ones.

| Field | Required? | Type / constraint |
|---|---|---|
| `id` | ✅ | string, unique |
| `name` | ✅ | string |
| `category` | ✅ | one of the known store categories (see §5.1) |
| `price` | ✅ | int ≥ 0 |
| `width_cm` | ✅ | float, 0 < w ≤ 1000 |
| `depth_cm` | ✅ | float, 0 < d ≤ 1000 |
| `height_cm` | ✅ | float, 0 < h ≤ 400 |
| `style_tags` | ✅ | list of the constrained `StyleTag` set |
| `colors` | ✅ | list[string] |
| `image_url` | optional | string (default `""`) |
| `two_d_icon` | optional | string (default `""`) — but see the hygiene gate |
| `is_walkable` | optional | bool (default `false`) — **derived** |
| `shape` | optional | `"rect"` \| `"round"` (default `"rect"`) — **derived** |
| `room_types` | optional | list of `"living_room"` \| `"bedroom"` \| `"majlis"` — **derived (override-able)** |
| `seating_capacity` | optional | int ≥ 0 (default 0) — **derived** |
| `styles` | optional | list[string] (free-form) |
| `main_color` | optional | string |
| `secondary_colors` | optional | list[string] |
| `main_family` | optional | string — **derived** |

---

## 3. Load pipeline (run per row)

```
Stage 0  SELECT              — SQL: is_active, and (optionally) two_d_icon IS NOT NULL
Stage 1  HYGIENE GATE        — drop unusable rows, count the reason (§6)
Stage 2  NORMALIZE           — dimensions → cm (§5.9); parse price
Stage 3  MAP & DERIVE        — category→role and everything keyed off it (§5)
Stage 4  VALIDATE            — build Product (strict); on failure, drop + log
```

Every drop is **counted by reason** and logged as a summary (mirrors the importer's `rejects`
`Counter`), so data-quality regressions are visible, never silent.

---

## 4. Direct column → field (no logic)

| `Product` field | DB column | note |
|---|---|---|
| `id` | `id` (prefix with store, e.g. `ikea-83963`, to stay globally unique) | |
| `name` | `name_english` | trim quotes/space |
| `category` | `category` | must map in §5.1, else drop |
| `price` | `price_amount` | `int(round(float(...)))` |
| `colors` | `[main_color, *secondary_colors]` deduped; `["Natural"]` if empty | |
| `image_url` | `image_url` | |
| `two_d_icon` | `two_d_icon` | prefix the S3 base if it's a relative key |
| `styles` | `styles` | comma-split, trimmed |
| `main_color` | `main_color` | |
| `secondary_colors` | `secondary_colors` | comma-split |

---

## 5. Derived fields — the mappings (these live in **loader code**, not DB columns)

### 5.1 `category` → placement **role** — the keystone (`PLACEMENT_GROUP`)

A row whose category isn't in this table is **unplaceable → drop it** (reason `unmapped:<category>`).
This is also the "specific category" filter.

| Store category | Role |
|---|---|
| `2-seater-sofa`, `3-seater-sofa`, `l-shape-sofa` | `sofa` |
| `chaise-lounge` | `chaise` *(standalone lounge — never selected as a sofa)* |
| `chair`, `office-chair` | `accent_chair` |
| `office-table` | `desk` *(loads; not placed until the work-nook rule ships)* |
| `dining-table` | `dining_table` *(loads; not placed until the dining rule ships)* |
| `tv-table` | `tv_unit` |
| `center-table` | `coffee_table` |
| `side-table`, `service-table` | `side_table` |
| `carpet` | `rug` |
| `console`, `shelve`, `storage-box`, `wardrobe`, `dressing-table` | `storage` |
| `wall-lighting`, `lampshade`, `floor-stand` | `lighting` |
| `art-canvas`, `decorative-hanger`, `flower-pot-and-plant`, `flower`, `vase`, `statue-and-antique`, `wall-clock` | `decor` |
| `bed` | `bed` |

> The engine keys off the **role**; per room it narrows a role back to a preferred store category
> (`ROOM_CATEGORY_PREFERENCE`, e.g. living-room `storage → console`, bedroom `storage → wardrobe`).
> That's engine logic, not loader logic — just preserve the original `category` on each product.

### 5.2 `shape` — `"round"` if role ∈ {`decor`} else `"rect"`.

### 5.3 `is_walkable` — `true` if role ∈ {`rug`} else `false`.

### 5.4 `seating_capacity`
```
sofa         → max(1, round(width_cm / 75))
accent_chair → 1
everything else → 0
```

### 5.5 `room_types` (override-able — see §7)
```
room_types = []
if role ∈ LIVING_ROLES:  room_types += ["living_room"]
if role ∈ BEDROOM_ROLES: room_types += ["bedroom"]
if empty:                room_types  = ["living_room"]
```
- `LIVING_ROLES`  = sofa, tv_unit, rug, coffee_table, side_table, accent_chair, lighting, storage, decor, dining_table, desk, chaise
- `BEDROOM_ROLES` = bed, side_table, storage, lighting, decor, rug, accent_chair, tv_unit, desk

### 5.6 `height_cm`
Prefer the DB `height` (normalized to cm, in range `0 < h ≤ 400`). If missing/out-of-range, fall
back to a per-role default (`ROLE_HEIGHT`):

| role | sofa | accent_chair | tv_unit | coffee_table | side_table | rug | storage | lighting | decor | bed | dining_table | desk | chaise |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cm | 85 | 90 | 50 | 45 | 55 | 1 | 180 | 150 | 35 | 45 | 75 | 75 | 85 |

> The current importer **always** synthesizes height. Decide per your data whether the DB `height` is
> trustworthy; if not, keep synthesizing.

### 5.7 `style_tags` (override-able — see §7)
Map each free-form `styles` entry into the constrained `StyleTag` vocabulary; dedupe; default to
`["modern"]` if nothing maps (`STYLE_TAG_MAP`):

| source style | → StyleTag |
|---|---|
| Modern, Rustic_Modern, Mid_Century, Contemporary, Coastal, Eclectic | `modern` |
| Minimalist, Zen | `minimal` |
| Modern_Classic, Traditional, Classy, Shabby_Chic | `classic` |
| Scandinavian | `scandinavian` |
| Boho, Tropical | `boho` |
| Industrial | `industrial` |
| Islamic | `saudi_traditional` |
| Moroccan | `arabic` |

### 5.8 `main_family` — `family_of(main_color)` (a named-colour → palette-family lookup; `""` if unknown).

### 5.9 Dimension normalization + `footprint`
1. **To cm:** `value_cm = raw * UNIT_CM[dimension_unit]`, where `UNIT_CM = {cm:1, mm:0.1, m:100, in/inch:2.54, "" :1}`.
2. **Footprint:** with `lo=min(w,l)`, `hi=max(w,l)` — for `bed`, `width=lo, depth=hi`; **all other roles**,
   `width=hi, depth=lo`. Then **clamp** each to the role's sane range (`ROLE_DIMS[role] = (w_min, w_max, d_min, d_max)`),
   e.g. `sofa (140–320 × 70–105)`, `rug (120–400 × 80–350)`, `bed (90–200 × 190–215)`. Clamping keeps the
   engine's fit/scoring logic well-behaved on dirty rows.

---

## 6. Hygiene gate — drop rules (each drop counted + logged)

| Reason | Condition |
|---|---|
| `no_icon` | `two_d_icon` empty (your "only products with icons" rule) |
| `drop_category:<c>` | category ∈ {`comforter`, `bedspread`, `mattresses`, `pillow`} (soft goods) |
| `unmapped:<c>` | category not in `PLACEMENT_GROUP`, or its role has no `ROLE_DIMS` |
| `accessory:<c>` | name matches the spare-part regex (cover, runner, placemat, cushion cover, photo/picture frame, module, spare, …) |
| `bad_number` | width/length missing or non-numeric |
| `corrupt_or_undersized:<c>` | `min(w,l) < 3`, or `max(w,l) > 400`, or (dining_table `< 120` / desk `< 80` longest side) |
| `bad_price` | `price_amount` missing/non-numeric |
| `duplicate_id` | id already seen |

---

## 7. Optional override columns (only if you want human curation)

Follow the existing "fill-only-when-absent" contract: **if the DB column is non-null, use it; else
derive.** Two fields justify this:

- **`room_types`** — the default is role-derived, but some SKUs need explicit tagging (e.g. beds/chairs
  hand-tagged bedroom-only). Also the one field you might want to filter on server-side
  (`WHERE 'bedroom' = ANY(room_types)`), which is the only real case for making it a stored column.
- **`style_tags`** — the `styles → StyleTag` map is fuzzy/curatorial; a column lets merchandisers
  override it.

Everything else in §5 (`shape`, `is_walkable`, `seating_capacity`, `main_family`, footprint, height
default) is a pure function of data already in the row — **keep it in code, never a stored column**, so
an engine-logic change never leaves stale denormalized values behind.

---

## 8. Explicitly NOT stored / NOT read

Removed from the model entirely (do **not** add columns for these): `brand, mrp, materials, in_stock,
delivery_days, rating, attrs, description, placement_type, is_modular, formality, luxury_tier, region`.
`price` stays as data (response totals + the selector's cheapest-on-tie tie-break) but is **not** a
scoring dimension.
