"""Import the real Salla/store catalog (Django dumpdata export) into our Product schema.

Reads products_export.json (core.product rows), CLEANS messy data (drops covers/parts,
rejects absurd dimensions), MAPS the 53 source categories onto our 10, and BACKFILLS the
taxonomy our recommender needs (height, seating, placement, room_types, style hints).
2D icons are referenced by public URL. Writes a candidate catalog + prints a quality
report. Does NOT touch the live catalog - that's a separate, reviewed step.

Usage: python scripts/import_real_catalog.py <products_export.json> <out.json>
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

ICON_BASE = "https://zory-temporary-uploads-backup.s3.ap-south-1.amazonaws.com"
SAR_PER_USD = 3.75  # catalog amounts are stored in base currency (USD); the UI shows SAR

# source category -> our category
CAT_MAP = {
    "sofa": "sofa", "2-seater-sofa": "sofa", "3-seater-sofa": "sofa", "l-shape-sofa": "sofa",
    "bed": "bed",
    "chair": "accent_chair",
    "side-table": "side_table",
    "center-table": "coffee_table",
    "tv-table": "tv_unit",
    "console": "storage", "shelve": "storage", "storage-box": "storage",
    "carpet": "rug",
    "lighting": "lighting", "lampshade": "lighting",
    "vase": "decor", "art-canvas": "decor", "candle": "decor",
}

# our category -> (w_range, d_range, height_cm, orient, seats, placement, walkable, shape, room_types)
CAT_CFG = {
    "sofa": ((120, 360), (60, 130), 85, "wide", 3, "wall_hug", False, "rect", ["living_room", "majlis"]),
    "bed": ((80, 220), (180, 230), 50, "deep", 0, "wall_hug", False, "rect", ["bedroom"]),
    "accent_chair": ((40, 100), (40, 100), 85, "square", 1, "freestanding", False, "rect", ["living_room", "bedroom"]),
    "side_table": ((25, 90), (25, 90), 55, "square", 0, "freestanding", False, "rect", ["living_room", "bedroom"]),
    "coffee_table": ((55, 160), (40, 120), 45, "wide", 0, "floor", False, "rect", ["living_room"]),
    "tv_unit": ((80, 300), (28, 62), 55, "wide", 0, "wall_hug", False, "rect", ["living_room"]),
    "storage": ((40, 260), (28, 72), 120, "wide", 0, "wall_hug", False, "rect", ["living_room", "bedroom"]),
    "rug": ((100, 500), (80, 400), 1, "wide", 0, "floor", True, "rect", ["living_room", "bedroom"]),
    "lighting": ((15, 90), (15, 90), 140, "square", 0, "freestanding", False, "round", ["living_room", "bedroom"]),
    "decor": ((10, 80), (10, 80), 35, "square", 0, "freestanding", False, "rect", ["living_room", "bedroom"]),
}

# names that are accessories / parts, not placeable furniture
JUNK = re.compile(r"\b(cover|slipcover|spare|replacement|knob|handle|leg|legs|cushion cover|"
                  r"armrest|cover for|frame only|topper|protector|sticker|decal)\b", re.I)
UNIT_TO_CM = {"cm": 1.0, "mm": 0.1, "m": 100.0, "in": 2.54, "": 1.0, None: 1.0}
STYLE_KW = {
    "modern": "modern", "contemporary": "modern", "scandinav": "scandinavian", "scandi": "scandinavian",
    "industrial": "industrial", "boho": "boho", "bohemian": "boho", "classic": "classic",
    "traditional": "classic", "minimal": "minimal", "luxur": "luxury", "luxe": "luxury",
    "arabic": "arabic", "majlis": "majlis",
}


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def orient(L, W, mode):
    big, small = max(L, W), min(L, W)
    if mode == "wide":
        return big, small  # width along the wall, depth into the room
    if mode == "deep":
        return small, big  # bed: narrow headboard width, long head-to-foot depth
    return W, L  # square-ish: keep as given


def styles_from_name(name):
    low = name.lower()
    out = []
    for kw, tag in STYLE_KW.items():
        if kw in low and tag not in out:
            out.append(tag)
    return out[:3]


def seats_for(src_cat, name):
    if src_cat == "l-shape-sofa":
        return 4
    if src_cat == "2-seater-sofa":
        return 2
    if src_cat == "3-seater-sofa":
        return 3
    m = re.search(r"(\d)\s*-?\s*seat", name.lower())
    return int(m.group(1)) if m else 3  # plain "sofa" -> assume 3-seat


def brand_from_icon(icon_key):
    parts = (icon_key or "").split("/")
    if len(parts) >= 2 and parts[0].lower() == "2d_icons":
        return parts[1].replace("-", " ").title()
    return "Zory"


# The source "console"/"shelve"/"storage-box" categories are a grab-bag (media consoles,
# console tables, dressers, sideboards, cabinets, bookshelves, even nightstands). Mapping
# them all to "storage" makes the storage slot pick a media/console piece that duplicates
# the TV unit. Refine by product name so the room never gets two TV-stand-type pieces.
_NIGHTSTAND_KW = re.compile(r"night\s?stand|bedside", re.I)
_STORAGE_KW = re.compile(
    r"dresser|sideboard|buffet|credenza|cabinet|bookcase|book\s?shelf|shelf|shelv|"
    r"wardrobe|drawer|chest|cupboard|hutch|armoire", re.I,
)
_MEDIA_KW = re.compile(r"\btv\b|television|entertainment|media", re.I)


def refine_category(src: str, our: str, name: str) -> str:
    """Disambiguate the storage/tv_unit bucket by product name (catalog data is messy)."""
    if our not in ("storage", "tv_unit"):
        return our
    if _NIGHTSTAND_KW.search(name):
        return "side_table"  # a nightstand is a small side table, not living-room storage
    if _STORAGE_KW.search(name):
        return "storage"  # real storage: dresser / sideboard / cabinet / bookshelf
    if _MEDIA_KW.search(name):
        return "tv_unit"  # media / entertainment console
    if src == "console":
        return "tv_unit"  # generic console / console table -> a media surface, not a 2nd storage
    return our


def convert(rows):
    out = []
    stats = Counter()
    rejected = Counter()
    for r in rows:
        if r.get("model") != "core.product":
            continue
        f = r["fields"]
        src = f.get("category")
        if src not in CAT_MAP:
            rejected["category_not_mapped"] += 1
            continue
        if not f.get("is_active"):
            rejected["inactive"] += 1
            continue
        icon = f.get("two_d_icon")
        if not icon:
            rejected["no_icon"] += 1
            continue
        name = (f.get("name_english") or "").strip()
        if not name or JUNK.search(name):
            rejected["junk_name"] += 1
            continue
        L, W = fnum(f.get("length")), fnum(f.get("width"))
        if not L or not W:
            rejected["no_dims"] += 1
            continue
        scale = UNIT_TO_CM.get(f.get("dimension_unit"), 1.0)
        L, W = L * scale, W * scale
        our = refine_category(src, CAT_MAP[src], name)
        (wlo, whi), (dlo, dhi), height, mode, _seats, placement, walk, shape, rtypes = CAT_CFG[our]
        width, depth = orient(L, W, mode)
        if not (wlo <= width <= whi and dlo <= depth <= dhi):
            rejected[f"dims_out_of_range_{our}"] += 1
            continue
        price_sar = fnum(f.get("price_amount"))
        if not price_sar or price_sar <= 0 or price_sar > 1_000_000:
            rejected["bad_price"] += 1
            continue
        price = round(price_sar / SAR_PER_USD)  # store in base currency (USD); UI shows SAR
        st = styles_from_name(name)
        out.append({
            "id": f"p{r['pk']}",
            "name": name[:120],
            "brand": brand_from_icon(icon),
            "category": our,
            "price": round(price),
            "width_cm": round(width, 1),
            "depth_cm": round(depth, 1),
            "height_cm": float(height),
            "style_tags": st,
            "colors": [f["product_color"]] if f.get("product_color") else [],
            "materials": [],
            "in_stock": True,
            "delivery_days": 7,
            "rating": 4.3,
            "image_url": f.get("image_url") or "",
            "two_d_icon": f"{ICON_BASE}/{icon}" if not icon.startswith("http") else icon,
            "is_walkable": walk,
            "shape": shape,
            "room_types": rtypes,
            "placement_type": placement,
            "seating_capacity": seats_for(src, name) if our == "sofa" else (1 if our == "accent_chair" else 0),
            "region": "global",
        })
        stats[our] += 1
    return out, stats, rejected


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/haidermanzoor/Desktop/Zory_ai/backend/products_export.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "spatial_planning/data/catalog_real.json"
    rows = json.load(open(src_path))
    products, stats, rejected = convert(rows)
    json.dump(products, open(out_path, "w"), indent=1, ensure_ascii=False)

    print(f"=== IMPORT: {len(products)} products kept -> {out_path} ===")
    for cat, n in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {cat:14} {n}")
    print("--- rejected (why) ---")
    for why, n in rejected.most_common(12):
        print(f"  {why:28} {n}")
    print("--- sample kept ---")
    for p in products[:5]:
        print(f"  [{p['category']:11}] {p['width_cm']}x{p['depth_cm']}cm  SAR {p['price']:<6} {p['name'][:42]}  ({p['brand']})")


if __name__ == "__main__":
    main()
