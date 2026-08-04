"""Build a planner catalog JSON from the multi-store CSV (samples_4stores.csv).

Keeps each product's ORIGINAL store category (no collapsing) and lets the engine place
it via app.models.products.PLACEMENT_GROUP (store category -> placement role). Missing
fields (height, price, colours, room_types, ...) are synthesised; corrupt / mislabeled
rows and non-placeable categories are dropped. Prints a rejects report.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/build_store_catalog.py \
        ../samples_4stores.csv spatial_planning/data/catalog_stores.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter

from spatial_planning.models.products import PLACEMENT_GROUP

# The 2D-icon SVGs live in the same S3 bucket the existing catalog uses; the CSV carries the
# relative object key, so we make it absolute. The frontend icon proxy (/api/icon) already
# allow-lists this host, so these render straight onto the canvas.
ICON_BASE = "https://zory-temporary-uploads-backup.s3.ap-south-1.amazonaws.com"

# --- categories we do NOT place in the room (bedding sits on the bed; dining/office are
# out of the living/majlis/bedroom scope). Dropped entirely.
DROP_CATEGORIES = {"dining-table", "office-table", "comforter", "bedspread", "mattresses", "pillow"}

# --- rows whose NAME reveals a spare part / accessory mis-filed under a furniture category.
PART_NAME = re.compile(
    r"\b(cover|covers|armrest|headrest|footstool|sheet|fitted|bedlinen|duvet|pillowcase|"
    r"bath mat|section|module|spare|knob|cushion cover|slipcover)\b|photo frame|picture frame",
    re.I,
)

# --- per placement-role footprint clamp: (width_min, width_max, depth_min, depth_max) cm.
# width = the LONGER side (along the wall), depth = the SHORTER side, EXCEPT bed (inverted:
# headboard on the wall, so depth = the longer/bed-length side).
ROLE_DIMS = {
    "sofa": (140, 320, 70, 105),
    "accent_chair": (45, 95, 45, 95),
    "tv_unit": (90, 280, 30, 55),
    "coffee_table": (50, 150, 40, 90),
    "side_table": (25, 70, 25, 70),
    "rug": (120, 400, 80, 350),
    "storage": (40, 300, 30, 62),
    "lighting": (18, 60, 18, 60),
    "decor": (8, 120, 8, 120),
    "bed": (90, 200, 190, 215),  # (width along wall), (depth = bed length into room)
}
ROLE_HEIGHT = {
    "sofa": 85, "accent_chair": 90, "tv_unit": 50, "coffee_table": 45, "side_table": 55,
    "rug": 1, "storage": 180, "lighting": 150, "decor": 35, "bed": 45,
}
# synthesised price baseline per role (SAR), scaled by footprint vs a typical size.
ROLE_PRICE = {
    "sofa": 3200, "accent_chair": 900, "tv_unit": 1400, "coffee_table": 700, "side_table": 350,
    "rug": 600, "storage": 1500, "lighting": 400, "decor": 180, "bed": 2400,
}
ROLE_TYP_AREA = {  # cm^2 typical footprint used to scale price
    "sofa": 220 * 95, "accent_chair": 70 * 70, "tv_unit": 180 * 45, "coffee_table": 110 * 60,
    "side_table": 45 * 45, "rug": 240 * 170, "storage": 120 * 45, "lighting": 40 * 40,
    "decor": 40 * 40, "bed": 160 * 200,
}
WALKABLE_ROLES = {"rug"}
ROUND_ROLES = {"decor"}  # vases/plants read better as round; harmless default

MAJLIS_ROLES = {"sofa", "rug", "storage", "lighting", "decor"}
BEDROOM_ROLES = {"bed", "side_table", "storage", "lighting", "decor", "rug"}

COLOR_WORDS = [
    "beige", "grey", "gray", "white", "black", "brown", "blue", "green", "red", "pink",
    "orange", "purple", "yellow", "natural", "oak", "walnut", "birch", "anthracite",
    "turquoise", "gold", "silver", "ivory", "cream", "navy", "olive", "rust", "charcoal",
]
STORE_STYLE = {
    "ikea": ["scandinavian", "modern"],
    "mesaky": ["modern", "luxury"],
    "panhome": ["modern", "classic"],
    "cityw": ["modern"],
}


def clean_name(raw: str) -> str:
    return raw.strip().strip('"')


def parse_colors(name: str) -> list[str]:
    low = name.lower()
    seen: list[str] = []
    for w in COLOR_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", low) and w not in seen:
            seen.append("grey" if w == "gray" else w)
    return [c.title() for c in seen[:3]]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def footprint(role: str, w: float, l: float) -> tuple[float, float]:
    lo, hi = min(w, l), max(w, l)
    wmn, wmx, dmn, dmx = ROLE_DIMS[role]
    if role == "bed":
        width, depth = lo, hi  # bed width (short) along wall; length (long) into room
    else:
        width, depth = hi, lo  # longer side along the wall, shorter is depth
    return round(clamp(width, wmn, wmx), 1), round(clamp(depth, dmn, dmx), 1)


def is_corrupt(cat: str, w: float, l: float) -> bool:
    """A side too small to be that furniture, or absurdly large."""
    floors = {
        "2-seater-sofa": 60, "3-seater-sofa": 60, "sofa": 60, "l-shape-sofa": 70,
        "chaise-lounge": 55, "bed": 80, "chair": 35, "office-chair": 35, "tv-table": 25,
        "center-table": 30, "side-table": 20, "service-table": 20, "console": 20,
        "shelve": 18, "storage-box": 12, "wardrobe": 30, "dressing-table": 25, "carpet": 50,
    }
    fl = floors.get(cat, 3)
    return min(w, l) < fl or min(w, l) < 1 or max(w, l) > 400


def synth_price(role: str, w: float, d: float) -> int:
    base = ROLE_PRICE[role]
    ratio = (w * d) / max(ROLE_TYP_AREA[role], 1.0)
    price = int(round(clamp(base * (0.55 + 0.45 * ratio), base * 0.4, base * 3.0)))
    # round to a tidy figure
    return max(50, round(price / 10) * 10)


def build(csv_path: str) -> tuple[list[dict], Counter]:
    products: list[dict] = []
    rejects: Counter = Counter()
    for r in csv.DictReader(open(csv_path)):
        cat = r["category"].strip()
        name = clean_name(r["name_english"])
        store = r["store"].strip().lower()
        try:
            w, l = float(r["width"]), float(r["length"])
        except ValueError:
            rejects["bad_number"] += 1
            continue
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
        if is_corrupt(cat, w, l):
            rejects["corrupt_dims"] += 1
            continue

        width, depth = footprint(role, w, l)
        price = synth_price(role, width, depth)
        room_types = ["living_room"]
        if role in MAJLIS_ROLES:
            room_types.append("majlis")
        if role in BEDROOM_ROLES and "bedroom" not in room_types:
            room_types.append("bedroom")
        seats = max(1, round(width / 75.0)) if role == "sofa" else (1 if role == "accent_chair" else 0)

        products.append(
            {
                "id": f"{store}-{r['id']}",
                "name": name,
                "category": cat,  # ORIGINAL store category (kept)
                "price": price,
                "width_cm": width,
                "depth_cm": depth,
                "height_cm": ROLE_HEIGHT[role],
                "style_tags": STORE_STYLE.get(store, ["modern"]),
                "colors": parse_colors(name) or ["Natural"],
                "two_d_icon": f"{ICON_BASE}/{r['two_d_icon'].strip().lstrip('/')}" if r["two_d_icon"].strip() else "",
                "is_walkable": role in WALKABLE_ROLES,
                "shape": "round" if role in ROUND_ROLES else "rect",
                "room_types": room_types,
                "seating_capacity": seats,
            }
        )
    return products, rejects


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "../samples_4stores.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "spatial_planning/data/catalog_stores.json"
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
