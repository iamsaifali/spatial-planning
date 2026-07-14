"""Build a planner catalog JSON from the CLEANED product-metadata export.

Input: product_metadata_clean.csv (the cleaned product_metadata.xlsx — rows with a null
main_color/styles dropped, secondary_colors backfilled from main_color).

Unlike build_store_catalog.py (which SYNTHESISES colours/styles/prices from the product
name), this uses the REAL data the export carries: actual price_amount (SAR), main_color /
secondary_colors, styles, and the two_d_icon object key. Only height_cm is synthesised
(the export has none) and dimensions are unit-normalised + clamped to sane per-role ranges.

Output field shape mirrors the existing catalog_stores.json exactly.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/build_catalog_from_excel.py \
        ../product_metadata_clean.csv spatial_planning/data/catalog_from_excel.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter

from spatial_planning.models.products import PLACEMENT_GROUP
from spatial_planning.models.style_metadata import family_of

ICON_BASE = "https://zory-temporary-uploads-backup.s3.ap-south-1.amazonaws.com"

# store category -> engine style tag, derived from the existing catalog's single-style rows.
STYLE_TAG_MAP = {
    "Modern": "modern", "Minimalist": "minimal", "Modern_Classic": "classic",
    "Traditional": "classic", "Scandinavian": "scandinavian", "Rustic_Modern": "modern",
    "Boho": "boho", "Mid_Century": "modern", "Islamic": "saudi_traditional",
    "Classy": "classic", "Shabby_Chic": "classic", "Industrial": "industrial",
    "Contemporary": "modern", "Coastal": "modern", "Moroccan": "arabic",
    "Zen": "minimal", "Eclectic": "modern", "Tropical": "boho",
}

# dimension_unit -> factor to centimetres
UNIT_CM = {"cm": 1.0, "mm": 0.1, "m": 100.0, "in": 2.54, "inch": 2.54, "": 1.0, None: 1.0}

DROP_CATEGORIES = {"dining-table", "office-table", "comforter", "bedspread", "mattresses", "pillow"}
PART_NAME = re.compile(
    r"\b(cover|covers|armrest|headrest|footstool|sheet|fitted|bedlinen|duvet|pillowcase|"
    r"bath mat|section|module|spare|knob|cushion cover|slipcover)\b|photo frame|picture frame",
    re.I,
)

# per placement-role footprint clamp (width along wall, depth into room), cm
ROLE_DIMS = {
    "sofa": (140, 320, 70, 105), "accent_chair": (45, 95, 45, 95), "tv_unit": (90, 280, 30, 55),
    "coffee_table": (50, 150, 40, 90), "side_table": (25, 70, 25, 70), "rug": (120, 400, 80, 350),
    "storage": (40, 300, 30, 62), "lighting": (18, 60, 18, 60), "decor": (8, 120, 8, 120),
    "bed": (90, 200, 190, 215),
}
ROLE_HEIGHT = {
    "sofa": 85, "accent_chair": 90, "tv_unit": 50, "coffee_table": 45, "side_table": 55,
    "rug": 1, "storage": 180, "lighting": 150, "decor": 35, "bed": 45,
}
WALKABLE_ROLES = {"rug"}
ROUND_ROLES = {"decor"}
MAJLIS_ROLES = {"sofa", "rug", "storage", "lighting", "decor"}
BEDROOM_ROLES = {"bed", "side_table", "storage", "lighting", "decor", "rug"}


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def footprint(role: str, w: float, l: float) -> tuple[float, float]:
    lo, hi = min(w, l), max(w, l)
    wmn, wmx, dmn, dmx = ROLE_DIMS[role]
    if role == "bed":
        width, depth = lo, hi  # bed width (short) on wall; length (long) into room
    else:
        width, depth = hi, lo  # longer side along the wall, shorter is depth
    return round(clamp(width, wmn, wmx), 1), round(clamp(depth, dmn, dmx), 1)


def is_corrupt(cat: str, w: float, l: float) -> bool:
    floors = {
        "2-seater-sofa": 60, "3-seater-sofa": 60, "l-shape-sofa": 70, "bed": 80, "chair": 35,
        "tv-table": 25, "center-table": 30, "side-table": 20, "service-table": 20, "console": 20,
        "wardrobe": 30, "dressing-table": 25, "carpet": 50,
    }
    fl = floors.get(cat, 3)
    return min(w, l) < fl or min(w, l) < 1 or max(w, l) > 400


def split_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def build(csv_path: str) -> tuple[list[dict], Counter]:
    products: list[dict] = []
    rejects: Counter = Counter()
    seen_ids: set[str] = set()
    for r in csv.DictReader(open(csv_path)):
        cat = (r.get("category") or "").strip()
        name = (r.get("name_english") or "").strip().strip('"')
        store = (r.get("store_name") or "").strip()
        if cat in DROP_CATEGORIES:
            rejects[f"drop_category:{cat}"] += 1
            continue
        role = PLACEMENT_GROUP.get(cat)
        if role is None:
            rejects[f"unmapped:{cat}"] += 1
            continue
        if PART_NAME.search(name):
            rejects["mislabeled_part"] += 1
            continue
        try:
            factor = UNIT_CM.get((r.get("dimension_unit") or "").strip(), 1.0)
            w = float(r["width"]) * factor
            l = float(r["length"]) * factor
        except (ValueError, KeyError, TypeError):
            rejects["bad_number"] += 1
            continue
        if is_corrupt(cat, w, l):
            rejects["corrupt_dims"] += 1
            continue
        try:
            price = int(round(float(r["price_amount"])))
        except (ValueError, KeyError, TypeError):
            rejects["bad_price"] += 1
            continue

        pid = f"{store.lower()}-{r.get('id')}"
        if pid in seen_ids:
            rejects["duplicate_id"] += 1
            continue
        seen_ids.add(pid)

        width, depth = footprint(role, w, l)
        room_types = ["living_room"]
        if role in MAJLIS_ROLES:
            room_types.append("majlis")
        if role in BEDROOM_ROLES and "bedroom" not in room_types:
            room_types.append("bedroom")
        seats = max(1, round(width / 75.0)) if role == "sofa" else (1 if role == "accent_chair" else 0)

        styles = split_list(r.get("styles"))
        tags: list[str] = []
        for s in styles:
            t = STYLE_TAG_MAP.get(s)
            if t and t not in tags:
                tags.append(t)
        if not tags:
            tags = ["modern"]

        main_color = (r.get("main_color") or "").strip()
        secondary = split_list(r.get("secondary_colors"))
        colors: list[str] = []
        for c in [main_color, *secondary]:
            if c and c not in colors:
                colors.append(c)

        icon_key = (r.get("two_d_icon") or "").strip().lstrip("/")
        products.append(
            {
                "id": pid,
                "name": name,
                "brand": store,
                "category": cat,
                "price": price,
                "mrp": None,
                "width_cm": width,
                "depth_cm": depth,
                "height_cm": float(ROLE_HEIGHT[role]),
                "style_tags": tags,
                "colors": colors or ["Natural"],
                "materials": [],
                "in_stock": True,
                "delivery_days": 7,
                "rating": 4.3,
                "image_url": (r.get("image_url") or "").strip(),
                "two_d_icon": f"{ICON_BASE}/{icon_key}" if icon_key else "",
                "is_walkable": role in WALKABLE_ROLES,
                "shape": "round" if role in ROUND_ROLES else "rect",
                "description": f"{name} — from {store}." if name else f"From {store}.",
                "room_types": room_types,
                "seating_capacity": seats,
                "styles": styles,
                "main_color": main_color,
                "secondary_colors": secondary,
                "main_family": family_of(main_color),
            }
        )
    return products, rejects


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "../product_metadata_clean.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "spatial_planning/data/catalog_from_excel.json"
    products, rejects = build(src)
    json.dump(products, open(out, "w"), ensure_ascii=False, indent=2)

    by_role = Counter(PLACEMENT_GROUP[p["category"]] for p in products)
    by_cat = Counter(p["category"] for p in products)
    print(f"WROTE {len(products)} products -> {out}")
    print("\nby placement role:")
    for role, n in by_role.most_common():
        print(f"  {n:4} {role}")
    print("\nby store category (kept):")
    for c, n in by_cat.most_common():
        print(f"  {n:4} {c}")
    print(f"\nREJECTED {sum(rejects.values())} rows:")
    for reason, n in rejects.most_common():
        print(f"  {n:4} {reason}")


if __name__ == "__main__":
    main()
