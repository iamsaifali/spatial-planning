"""Build the planner catalog from extended_dataset.csv (the extended multi-store export).

Differences from build_catalog_from_excel.py:
  * the store is derived from the two_d_icon path (this export carries a numeric store_id,
    not a store name), e.g. "2D_icons/ikea/83963.svg" -> "ikea";
  * dining-table and office-table are NO LONGER dropped (they now have Category entries and a
    placement role) - but they have no recipe rule yet, so they load and simply aren't placed;
  * dining-table is cleaned of placemats / runners / accessories and undersized rows;
  * the new roles (dining_table, desk) get footprint + height synthesis.

Uses the REAL colours / styles / prices / icons the export carries. Only height is synthesised.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/build_catalog_extended.py \
        ../extended_dataset.csv spatial_planning/data/catalog_extended.json
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

STYLE_TAG_MAP = {
    "Modern": "modern", "Minimalist": "minimal", "Modern_Classic": "classic",
    "Traditional": "classic", "Scandinavian": "scandinavian", "Rustic_Modern": "modern",
    "Boho": "boho", "Mid_Century": "modern", "Islamic": "saudi_traditional",
    "Classy": "classic", "Shabby_Chic": "classic", "Industrial": "industrial",
    "Contemporary": "modern", "Coastal": "modern", "Moroccan": "arabic",
    "Zen": "minimal", "Eclectic": "modern", "Tropical": "boho",
}
UNIT_CM = {"cm": 1.0, "mm": 0.1, "m": 100.0, "in": 2.54, "inch": 2.54, "": 1.0, None: 1.0}

# soft goods that sit on the bed / kitchen items - never placed as furniture
DROP_CATEGORIES = {"comforter", "bedspread", "mattresses", "pillow"}

# spare parts / accessories mis-filed under a furniture category (esp. dining-table)
PART_NAME = re.compile(
    r"\b(cover|covers|armrest|headrest|footstool|sheet|fitted|bedlinen|duvet|pillowcase|"
    r"section|module|spare|knob|cushion cover|slipcover|placemat|place mat|table mat|"
    r"tablecloth|table cloth|runner|napkin|coaster|centerpiece|centrepiece|cutlery|"
    r"utensil|serving|tray)\b|photo frame|picture frame",
    re.I,
)

ROLE_DIMS = {
    "sofa": (140, 320, 70, 105), "accent_chair": (45, 95, 45, 95), "tv_unit": (90, 280, 30, 55),
    "coffee_table": (50, 150, 40, 90), "side_table": (25, 70, 25, 70), "rug": (120, 400, 80, 350),
    "storage": (40, 300, 30, 62), "lighting": (18, 60, 18, 60), "decor": (8, 120, 8, 120),
    "bed": (90, 200, 190, 215),
    "dining_table": (120, 280, 75, 120), "desk": (90, 200, 42, 85),
    "chaise": (120, 250, 55, 120),
}
ROLE_HEIGHT = {
    "sofa": 85, "accent_chair": 90, "tv_unit": 50, "coffee_table": 45, "side_table": 55,
    "rug": 1, "storage": 180, "lighting": 150, "decor": 35, "bed": 45,
    "dining_table": 75, "desk": 75, "chaise": 85,
}
# a piece of this role whose LONGEST side is below this is an accessory, not the furniture
MIN_MAX_DIM = {"dining_table": 120.0, "desk": 80.0}

WALKABLE_ROLES = {"rug"}
ROUND_ROLES = {"decor"}
LIVING_ROLES = {"sofa", "tv_unit", "rug", "coffee_table", "side_table", "accent_chair",
                "lighting", "storage", "decor", "dining_table", "desk", "chaise"}
BEDROOM_ROLES = {"bed", "side_table", "storage", "lighting", "decor", "rug", "accent_chair",
                 "tv_unit", "desk"}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def footprint(role, w, l):
    lo, hi = min(w, l), max(w, l)
    wmn, wmx, dmn, dmx = ROLE_DIMS[role]
    if role == "bed":
        width, depth = lo, hi
    else:
        width, depth = hi, lo
    return round(clamp(width, wmn, wmx), 1), round(clamp(depth, dmn, dmx), 1)


def is_corrupt(role, w, l):
    return min(w, l) < 3 or max(w, l) > 400 or (role in MIN_MAX_DIM and max(w, l) < MIN_MAX_DIM[role])


def split_list(raw):
    if not raw:
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def store_of(icon):
    if "2D_icons/" in (icon or ""):
        return icon.split("2D_icons/")[-1].split("/")[0].strip().lower()
    return ""


def build(csv_path):
    products, rejects = [], Counter()
    seen = set()
    for r in csv.DictReader(open(csv_path)):
        cat = (r.get("category") or "").strip()
        name = (r.get("name_english") or "").strip().strip('"')
        store = store_of(r.get("two_d_icon"))
        if not store:
            rejects["no_store"] += 1
            continue
        if cat in DROP_CATEGORIES:
            rejects[f"drop_category:{cat}"] += 1
            continue
        role = PLACEMENT_GROUP.get(cat)
        if role is None or role not in ROLE_DIMS:
            rejects[f"unmapped:{cat}"] += 1
            continue
        if PART_NAME.search(name):
            rejects[f"accessory:{cat}"] += 1
            continue
        try:
            factor = UNIT_CM.get((r.get("dimension_unit") or "").strip(), 1.0)
            w = float(r["width"]) * factor
            l = float(r["length"]) * factor
        except (ValueError, KeyError, TypeError):
            rejects["bad_number"] += 1
            continue
        if is_corrupt(role, w, l):
            rejects[f"corrupt_or_undersized:{cat}"] += 1
            continue
        try:
            price = int(round(float(r["price_amount"])))
        except (ValueError, KeyError, TypeError):
            rejects["bad_price"] += 1
            continue

        pid = f"{store}-{r.get('id')}"
        if pid in seen:
            rejects["duplicate_id"] += 1
            continue
        seen.add(pid)

        width, depth = footprint(role, w, l)
        room_types = []
        if role in LIVING_ROLES:
            room_types.append("living_room")
        if role in BEDROOM_ROLES:
            room_types.append("bedroom")
        if not room_types:
            room_types = ["living_room"]
        seats = max(1, round(width / 75.0)) if role == "sofa" else (1 if role == "accent_chair" else 0)

        styles = split_list(r.get("styles"))
        tags = []
        for s in styles:
            t = STYLE_TAG_MAP.get(s)
            if t and t not in tags:
                tags.append(t)
        if not tags:
            tags = ["modern"]

        main_color = (r.get("main_color") or "").strip()
        secondary = split_list(r.get("secondary_colors"))
        colors = []
        for c in [main_color, *secondary]:
            if c and c not in colors:
                colors.append(c)

        icon_key = (r.get("two_d_icon") or "").strip().lstrip("/")
        products.append({
            "id": pid, "name": name, "category": cat,
            "price": price,
            "width_cm": width, "depth_cm": depth, "height_cm": float(ROLE_HEIGHT[role]),
            "style_tags": tags, "colors": colors or ["Natural"],
            "image_url": (r.get("image_url") or "").strip(),
            "two_d_icon": f"{ICON_BASE}/{icon_key}" if icon_key else "",
            "is_walkable": role in WALKABLE_ROLES,
            "shape": "round" if role in ROUND_ROLES else "rect",
            "room_types": room_types, "seating_capacity": seats,
            "styles": styles, "main_color": main_color, "secondary_colors": secondary,
            "main_family": family_of(main_color),
        })
    return products, rejects


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "../extended_dataset.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "spatial_planning/data/catalog_extended.json"
    products, rejects = build(src)
    json.dump(products, open(out, "w"), ensure_ascii=False, indent=2)

    by_role = Counter(PLACEMENT_GROUP.get(p["category"], p["category"]) for p in products)
    by_cat = Counter(p["category"] for p in products)
    print(f"WROTE {len(products)} products -> {out}")
    print("\nby placement role:")
    for role, n in by_role.most_common():
        print(f"  {n:5} {role}")
    print("\nby store category:")
    for c, n in by_cat.most_common():
        print(f"  {n:5} {c}")
    print(f"\nREJECTED {sum(rejects.values())}:")
    for reason, n in rejects.most_common():
        print(f"  {n:5} {reason}")


if __name__ == "__main__":
    main()
