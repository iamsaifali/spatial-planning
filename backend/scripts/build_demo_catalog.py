"""Build the planner catalog JSON from demo_products.csv (4 real stores, with metadata).

Unlike build_store_catalog.py, this CSV already carries REAL prices and the generated style /
colour metadata (styles, main_color, secondary_colors), so we import those verbatim instead of
synthesising them. We still:
  - keep each product's ORIGINAL store category (placed via PLACEMENT_GROUP),
  - derive width_cm/depth_cm from max/min of the two dims (the CSV length/width labels are only
    ~80% consistent), INVERTING the bed (headboard = short side on the wall, bed-length into room),
  - clamp footprints per placement role and drop rows with corrupt dims / accessory names,
  - map the free-form `styles` onto the legacy StyleTag enum for the existing style scoring,
  - snap main_color -> main_family via app.models.style_metadata,
  - make the 2D-icon relative key absolute (same S3 bucket the icon proxy already allow-lists).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/build_demo_catalog.py \
        ../demo_products.csv app/data/catalog_stores.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter

from app.models.products import PLACEMENT_GROUP
from app.models.style_metadata import STYLES, family_of

ICON_BASE = "https://zory-temporary-uploads-backup.s3.ap-south-1.amazonaws.com"

DROP_CATEGORIES = {"dining-table", "office-table", "comforter", "bedspread", "mattresses", "pillow"}
PART_NAME = re.compile(
    r"\b(cover|covers|armrest|headrest|footstool|sheet|fitted|bedlinen|duvet|pillowcase|"
    r"bath mat|section|module|spare|knob|cushion cover|slipcover)\b|photo frame|picture frame",
    re.I,
)

# (width_min, width_max, depth_min, depth_max) cm per placement role. width = the side along the
# wall, depth = perpendicular. bed is inverted in footprint() (headboard on wall).
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
    "bed": (90, 200, 190, 215),
}
ROLE_HEIGHT = {  # fallback when the CSV height is blank (blank in ~77% of rows)
    "sofa": 85, "accent_chair": 90, "tv_unit": 50, "coffee_table": 45, "side_table": 55,
    "rug": 1, "storage": 180, "lighting": 150, "decor": 35, "bed": 45,
}
WALKABLE_ROLES = {"rug"}
ROUND_ROLES = {"decor"}

MAJLIS_ROLES = {"sofa", "rug", "storage", "lighting", "decor"}
BEDROOM_ROLES = {"bed", "side_table", "storage", "lighting", "decor", "rug"}

# Free-form catalog style -> the legacy StyleTag vocabulary (drives the existing style scoring).
# The rich names are preserved separately on Product.styles.
STYLE_TO_TAG = {
    "Modern": "modern", "Contemporary": "modern", "Rustic_Modern": "modern",
    "Eclectic": "modern", "Coastal": "modern", "Mid_Century": "modern", "Japandi": "minimal",
    "Minimalist": "minimal", "Zen": "minimal",
    "Scandinavian": "scandinavian", "Industrial": "industrial", "Boho": "boho", "Tropical": "boho",
    "Classy": "classic", "Modern_Classic": "classic", "Traditional": "classic",
    "Shabby_Chic": "classic", "Islamic": "saudi_traditional", "Moroccan": "arabic",
}


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
    floors = {
        "2-seater-sofa": 60, "3-seater-sofa": 60, "sofa": 60, "l-shape-sofa": 70,
        "chaise-lounge": 55, "bed": 80, "chair": 35, "office-chair": 35, "tv-table": 25,
        "center-table": 30, "side-table": 20, "service-table": 20, "console": 20,
        "shelve": 18, "storage-box": 12, "wardrobe": 30, "dressing-table": 25, "carpet": 50,
    }
    fl = floors.get(cat, 3)
    return min(w, l) < fl or min(w, l) < 1 or max(w, l) > 400


def parse_styles(raw: str) -> list[str]:
    """Split the CSV styles cell, keep only known style names, preserve order/dedupe."""
    out: list[str] = []
    for s in (raw or "").split(","):
        s = s.strip()
        if s in STYLES and s not in out:
            out.append(s)
    return out


def parse_colors(raw: str) -> list[str]:
    out: list[str] = []
    for c in (raw or "").split(","):
        c = c.strip()
        if c and c not in out:
            out.append(c)
    return out


def style_tags(styles: list[str]) -> list[str]:
    tags: list[str] = []
    for s in styles:
        t = STYLE_TO_TAG.get(s)
        if t and t not in tags:
            tags.append(t)
    return tags or ["modern"]


def room_types_for(cat: str, role: str) -> list[str]:
    # l-shape-sofa is a majlis perimeter piece: keep it in the catalog but out of living rooms.
    if cat == "l-shape-sofa":
        return ["majlis"]
    rt = ["living_room"]
    if role in MAJLIS_ROLES:
        rt.append("majlis")
    if role in BEDROOM_ROLES:
        rt.append("bedroom")
    return rt


def build(csv_path: str) -> tuple[list[dict], Counter]:
    products: list[dict] = []
    rejects: Counter = Counter()
    for r in csv.DictReader(open(csv_path)):
        cat = r["category"].strip()
        name = r["name_english"].strip().strip('"')
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
        try:
            price = max(0, int(round(float(r["price_amount"]))))
        except (ValueError, KeyError):
            rejects["bad_price"] += 1
            continue
        try:
            height = float(r["height"]) if r.get("height", "").strip() else float(ROLE_HEIGHT[role])
        except ValueError:
            height = float(ROLE_HEIGHT[role])
        height = clamp(height, 1.0, 400.0)

        styles = parse_styles(r.get("styles", ""))
        main_color = (r.get("main_color", "") or "").strip()
        secondary_colors = parse_colors(r.get("secondary_colors", ""))
        colors = [c for c in ([main_color] + secondary_colors) if c]
        seats = max(1, round(width / 75.0)) if role == "sofa" else (1 if role == "accent_chair" else 0)

        products.append(
            {
                "id": f"{store}-{r['id']}",
                "name": name,
                "brand": store.capitalize(),
                "category": cat,
                "price": price,
                "mrp": None,
                "width_cm": width,
                "depth_cm": depth,
                "height_cm": round(height, 1),
                "style_tags": style_tags(styles),
                "colors": colors or ["Natural"],
                "materials": [],
                "in_stock": True,
                "delivery_days": 7,
                "rating": 4.0,
                "image_url": (r.get("image_url", "") or "").strip(),
                "two_d_icon": f"{ICON_BASE}/{r['two_d_icon'].strip().lstrip('/')}" if r["two_d_icon"].strip() else "",
                "is_walkable": role in WALKABLE_ROLES,
                "shape": "round" if role in ROUND_ROLES else "rect",
                "description": f"{name} — from {store.capitalize()}.",
                "room_types": room_types_for(cat, role),
                "seating_capacity": seats,
                # style / colour metadata
                "styles": styles,
                "main_color": main_color,
                "secondary_colors": secondary_colors,
                "main_family": family_of(main_color),
            }
        )
    return products, rejects


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "../demo_products.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "app/data/catalog_stores.json"
    products, rejects = build(src)
    json.dump(products, open(out, "w"), ensure_ascii=False, indent=2)

    by_role = Counter(PLACEMENT_GROUP[p["category"]] for p in products)
    by_cat = Counter(p["category"] for p in products)
    no_family = sum(1 for p in products if not p["main_family"])
    no_styles = sum(1 for p in products if not p["styles"])
    print(f"WROTE {len(products)} products -> {out}")
    print("\nby placement role:")
    for role, n in by_role.most_common():
        print(f"  {n:4} {role}")
    print("\nby store category (kept):")
    for c, n in by_cat.most_common():
        print(f"  {n:4} {c}")
    print(f"\nmetadata: {no_family} missing main_family, {no_styles} missing styles")
    print(f"\nREJECTED {sum(rejects.values())} rows:")
    for reason, n in rejects.most_common():
        print(f"  {n:4} {reason}")


if __name__ == "__main__":
    main()
