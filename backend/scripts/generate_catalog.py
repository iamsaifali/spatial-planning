"""Regenerates app/data/catalog.json (committed seed data).

Deterministic: same script -> same catalog. Run from the backend directory:
    .venv/bin/python scripts/generate_catalog.py
"""

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "catalog.json"

rng = random.Random(2026)

UNSPLASH = "https://images.unsplash.com/{pid}?w=800&q=80&auto=format&fit=crop"

# Curated furniture photo pools per category (rotated across products).
PHOTOS = {
    "sofa": [
        "photo-1555041469-a586c61ea9bc",
        "photo-1493663284031-b7e3aefcae8e",
        "photo-1540574163026-643ea20ade25",
        "photo-1512212621149-107ffe572d2f",
        "photo-1567016432779-094069958ea5",
        "photo-1550254478-ead40cc54513",
        "photo-1484101403633-562f891dc89a",
        "photo-1519961655809-34fa156820ff",
    ],
    "tv_unit": [
        "photo-1593359677879-a4bb92f829d1",
        "photo-1581539250439-c96689b516dd",
        "photo-1595428774223-ef52624120d2",
        "photo-1601760562234-9814eea6663a",
    ],
    "rug": [
        "photo-1600166898405-da9535204843",
        "photo-1531835551805-16d864c8d311",
        "photo-1575414003591-ece8d0416c7a",
        "photo-1600607686527-6fb886090705",
    ],
    "coffee_table": [
        "photo-1532372320572-cda25653a26d",
        "photo-1499933374294-4584851497cc",
        "photo-1533090481720-856c6e3c1fdc",
        "photo-1567538096630-e0c55bd6374c",
    ],
    "side_table": [
        "photo-1565191999001-551c187427bb",
        "photo-1611117775350-ac3950990985",
        "photo-1499933374294-4584851497cc",
    ],
    "accent_chair": [
        "photo-1506439773649-6e0eb8cfb237",
        "photo-1567538096621-38d2284b23ff",
        "photo-1592078615290-033ee584e267",
        "photo-1519947486511-46149fa0a254",
        "photo-1598300042247-d088f8ab3a91",
    ],
    "lighting": [
        "photo-1507473885765-e6ed057f782c",
        "photo-1513506003901-1e6a229e2d15",
        "photo-1543198126-a8ad8e47fb22",
        "photo-1565636192335-0a4cbfa1aaf8",
    ],
    "storage": [
        "photo-1594620302200-9a762244a156",
        "photo-1588447749191-315ebee5c4a8",
        "photo-1595428774223-ef52624120d2",
        "photo-1601760562234-9814eea6663a",
    ],
    "decor": [
        "photo-1485955900006-10f4d324d411",
        "photo-1463320726281-696a485928c7",
        "photo-1416879595882-3373a0480b5b",
        "photo-1545165375-1b744b9ed444",
        "photo-1581783898377-1c85bf937427",
        "photo-1526057565006-20beab8dd2ed",
    ],
}

BRANDS = ["Aralia", "Mistwood", "Casa Norte", "Studio Kova", "Fern & Oak", "Dhara Living", "Loom & Larch", "Vanna Home"]

NEUTRALS = ["Beige", "Ivory", "Warm Grey", "Charcoal", "Oat", "Sand"]
WOODS = ["Oak", "Walnut", "Teak", "Sheesham", "Mango Wood"]
ACCENTS = ["Olive", "Rust", "Terracotta", "Forest Green", "Mustard", "Clay"]

STYLES = ["modern", "scandinavian", "industrial", "boho", "classic", "minimal"]


def style_pair(primary: str) -> list[str]:
    affinities = {
        "modern": ["minimal", "industrial"],
        "scandinavian": ["minimal", "boho"],
        "industrial": ["modern"],
        "boho": ["scandinavian"],
        "classic": ["modern"],
        "minimal": ["scandinavian", "modern"],
    }
    if rng.random() < 0.55:
        return [primary, rng.choice(affinities[primary])]
    return [primary]


# The spec bands below were authored in INR; catalog amounts are stored in the
# backend's BASE_CURRENCY (USD), so bands are converted once here and snapped
# to retail-style $X9 price points.
LEGACY_INR_PER_USD = 83


def money(lo: int, hi: int) -> int:
    """Retail USD price point derived from the INR-authored band."""
    lo_usd = max(9, lo // LEGACY_INR_PER_USD)
    hi_usd = max(lo_usd + 10, hi // LEGACY_INR_PER_USD)
    base = rng.randint(lo_usd // 10, hi_usd // 10) * 10
    return max(9, base - 1)


def pick_colors(pool: list[str], n: int = 2) -> list[str]:
    return rng.sample(pool, k=min(n, len(pool)))


products: list[dict] = []
counters: dict[str, int] = {}


def add(category: str, name: str, w: float, d: float, h: float, price: int,
        materials: list[str], colors: list[str], style: str,
        attrs: dict | None = None, shape: str = "rect",
        is_walkable: bool = False, description: str = "") -> None:
    counters[category] = counters.get(category, 0) + 1
    idx = counters[category]
    pid = f"{category.replace('_', '-')}-{idx:03d}"
    pool = PHOTOS[category]
    # ~60% of items carry a list price 8-25% above the selling price
    mrp = None
    if rng.random() < 0.6:
        mrp = (round(price * rng.uniform(1.08, 1.25)) // 10) * 10 - 1
        if mrp <= price:
            mrp = price + 9
    products.append(
        {
            "id": pid,
            "name": name,
            "brand": rng.choice(BRANDS),
            "category": category,
            "price": price,
            "mrp": mrp,
            "width_cm": w,
            "depth_cm": d,
            "height_cm": h,
            "style_tags": style_pair(style),
            "colors": colors,
            "materials": materials,
            "in_stock": rng.random() > 0.1,
            "delivery_days": rng.choice([2, 3, 5, 7, 10, 14, 21]),
            "rating": round(rng.uniform(3.6, 4.9), 1),
            "attrs": attrs or {},
            "image_url": "",
            "source_image_url": UNSPLASH.format(pid=pool[(idx - 1) % len(pool)]),
            "is_walkable": is_walkable,
            "shape": shape,
            "description": description,
        }
    )


# --- Sofas (16) ---------------------------------------------------------------
sofa_specs = [
    ("Luna 3-Seater Sofa", 218, 92, 85, (64990, 94990), "modern"),
    ("Oslo 2-Seater Sofa", 168, 88, 82, (42990, 62990), "scandinavian"),
    ("Marlowe Fabric Sofa", 226, 95, 88, (74990, 109990), "classic"),
    ("Kova Compact Loveseat", 152, 84, 80, (28990, 42990), "minimal"),
    ("Ashwood 3-Seater", 232, 96, 90, (89990, 129990), "classic"),
    ("Nimbus Low Sofa", 210, 98, 76, (58990, 84990), "minimal"),
    ("Brontë Tufted Sofa", 224, 94, 92, (99990, 154990), "classic"),
    ("Haven Modular 3-Seater", 240, 100, 84, (109990, 159990), "modern"),
    ("Sora Linen Sofa", 196, 90, 83, (54990, 79990), "scandinavian"),
    ("Atlas Track-Arm Sofa", 214, 92, 86, (66990, 98990), "modern"),
    ("Juniper Boho Sofa", 200, 95, 88, (61990, 89990), "boho"),
    ("Forge Industrial Sofa", 206, 90, 84, (57990, 83990), "industrial"),
    ("Petite Studio Sofa", 158, 82, 80, (24990, 36990), "minimal"),
    ("Grand Riviera Sofa", 252, 102, 90, (129990, 189990), "classic"),
    ("Mira Curved Sofa", 222, 98, 82, (94990, 139990), "modern"),
    ("Elm Street Sofa", 186, 88, 84, (47990, 69990), "scandinavian"),
]
for name, w, d, h, (lo, hi), style in sofa_specs:
    add(
        "sofa", name, w, d, h, money(lo, hi),
        [rng.choice(["Linen", "Cotton Weave", "Velvet", "Boucle"]), rng.choice(WOODS)],
        pick_colors(NEUTRALS + ACCENTS[:2]), style,
        attrs={"seat_height_cm": rng.choice([42, 43, 44, 45]), "arm_height_cm": rng.choice([55, 58, 60, 62, 65])},
        description="A comfortable anchor for the seating zone.",
    )

# --- TV units (10) --------------------------------------------------------------
tv_specs = [
    ("Ledge Low TV Unit", 180, 40, 48, (24990, 39990), "modern"),
    ("Skandi Media Console", 160, 42, 52, (21990, 34990), "scandinavian"),
    ("Foundry TV Cabinet", 200, 45, 50, (32990, 54990), "industrial"),
    ("Aria Floating Console", 150, 35, 40, (18990, 28990), "minimal"),
    ("Heritage Media Unit", 210, 45, 55, (44990, 69990), "classic"),
    ("Cane Weave TV Unit", 170, 42, 50, (27990, 42990), "boho"),
    ("Slimline Console", 130, 38, 45, (12990, 19990), "minimal"),
    ("Grandview Media Wall", 220, 45, 54, (54990, 79990), "modern"),
    ("Tana Compact TV Stand", 120, 36, 46, (13990, 21990), "scandinavian"),
    ("Marlow TV Sideboard", 190, 44, 52, (36990, 56990), "classic"),
]
for name, w, d, h, (lo, hi), style in tv_specs:
    add(
        "tv_unit", name, w, d, h, money(lo, hi),
        [rng.choice(WOODS), rng.choice(["Matte Laminate", "Veneer", "Powder-coated Steel"])],
        pick_colors(WOODS + NEUTRALS[:3]), style,
        description="Media storage that keeps cables and clutter hidden.",
    )

# --- Rugs (12) ------------------------------------------------------------------
rug_specs = [
    ("Dune Handwoven Rug", 230, 160, (8990, 15990), "scandinavian"),
    ("Atlas Kilim Rug", 300, 200, (14990, 24990), "boho"),
    ("Mist Plush Rug", 240, 170, (10990, 18990), "minimal"),
    ("Ember Jute Rug", 270, 180, (7990, 13990), "boho"),
    ("Stone Wash Rug", 300, 240, (19990, 34990), "modern"),
    ("Loom Classic Rug", 350, 250, (29990, 64999), "classic"),
    ("Petite Weave Rug", 180, 120, (3499, 6999), "minimal"),
    ("Sahara Lines Rug", 290, 200, (15990, 27990), "modern"),
    ("Fjord Wool Rug", 310, 230, (24990, 44990), "scandinavian"),
    ("Terra Diamond Rug", 260, 180, (11990, 21990), "boho"),
    ("Slate Border Rug", 280, 190, (13990, 23990), "industrial"),
    ("Ivory Field Rug", 320, 240, (27990, 49990), "classic"),
]
for name, w, d, (lo, hi), style in rug_specs:
    add(
        "rug", name, w, d, 1.5, money(lo, hi),
        [rng.choice(["Wool", "Jute", "Cotton Flatweave", "Polypropylene"])],
        pick_colors(NEUTRALS + ACCENTS), style,
        is_walkable=True,
        description="Defines the seating zone and warms up the floor.",
    )

# --- Coffee tables (12) ----------------------------------------------------------
coffee_specs = [
    ("Orbit Round Coffee Table", 90, 90, 42, (14990, 24990), "modern", "round"),
    ("Ledger Oak Coffee Table", 120, 60, 44, (18990, 29990), "scandinavian", "rect"),
    ("Anvil Industrial Table", 110, 65, 42, (16990, 26990), "industrial", "rect"),
    ("Halo Nesting Tables", 80, 80, 40, (12990, 19990), "minimal", "round"),
    ("Estate Marble Table", 130, 70, 45, (32990, 49990), "classic", "rect"),
    ("Rattan Drum Table", 75, 75, 40, (9990, 15990), "boho", "round"),
    ("Slab Low Table", 125, 70, 38, (21990, 33990), "modern", "rect"),
    ("Pebble Oval Table", 115, 65, 41, (17990, 27990), "minimal", "round"),
    ("Trestle Wood Table", 105, 60, 43, (13990, 22990), "scandinavian", "rect"),
    ("Compact Studio Table", 70, 70, 40, (6990, 11990), "minimal", "round"),
    ("Carved Heritage Table", 120, 65, 45, (26990, 41990), "classic", "rect"),
    ("Iron Frame Table", 100, 60, 42, (11990, 18990), "industrial", "rect"),
]
for name, w, d, h, (lo, hi), style, shape in coffee_specs:
    add(
        "coffee_table", name, w, d, h, money(lo, hi),
        [rng.choice(WOODS), rng.choice(["Marble", "Glass", "Steel", "Cane"])],
        pick_colors(WOODS + NEUTRALS[:2]), style, shape=shape,
        description="Within easy reach of the sofa for everyday use.",
    )

# --- Side tables (10) -------------------------------------------------------------
side_specs = [
    ("Dot Side Table", 45, 45, 55, (4990, 8990), "minimal", "round"),
    ("Sheesham End Table", 50, 50, 58, (7990, 12990), "classic", "rect"),
    ("Wire Frame Table", 42, 42, 52, (3990, 6990), "industrial", "round"),
    ("Nordic Stool Table", 40, 40, 50, (4490, 7490), "scandinavian", "round"),
    ("Cane Top Side Table", 48, 48, 56, (6990, 10990), "boho", "round"),
    ("Cube Storage Table", 45, 45, 50, (8990, 14990), "modern", "rect"),
    ("Pedestal C-Table", 40, 38, 60, (5990, 9990), "modern", "rect"),
    ("Mini Marble Table", 38, 38, 52, (9990, 16990), "classic", "round"),
    ("Stack Tray Table", 46, 46, 54, (2499, 4990), "minimal", "round"),
    ("Drift Wood Table", 50, 45, 55, (10990, 19990), "boho", "rect"),
]
for name, w, d, h, (lo, hi), style, shape in side_specs:
    add(
        "side_table", name, w, d, h, money(lo, hi),
        [rng.choice(WOODS + ["Steel", "Marble"])],
        pick_colors(WOODS + NEUTRALS[:2]), style, shape=shape,
        description="Keeps essentials at arm's reach beside the seating.",
    )

# --- Accent chairs (10) ------------------------------------------------------------
chair_specs = [
    ("Wing Lounge Chair", 75, 80, 100, (24990, 39990), "classic"),
    ("Sling Leather Chair", 70, 75, 78, (29990, 49990), "industrial"),
    ("Boucle Barrel Chair", 78, 76, 82, (22990, 36990), "modern"),
    ("Rattan Lounge Chair", 72, 78, 84, (15990, 26990), "boho"),
    ("Oak Frame Armchair", 68, 72, 80, (18990, 29990), "scandinavian"),
    ("Petite Reading Chair", 65, 70, 85, (12990, 19990), "minimal"),
    ("Velvet Club Chair", 80, 82, 78, (32990, 52990), "classic"),
    ("Swivel Studio Chair", 74, 74, 80, (26990, 42990), "modern"),
    ("Cane Back Accent Chair", 66, 70, 88, (14990, 23990), "boho"),
    ("Recline Lounge Chair", 85, 85, 95, (44990, 69990), "modern"),
]
for name, w, d, h, (lo, hi), style in chair_specs:
    add(
        "accent_chair", name, w, d, h, money(lo, hi),
        [rng.choice(["Boucle", "Leather", "Velvet", "Cane", "Linen"]), rng.choice(WOODS)],
        pick_colors(NEUTRALS + ACCENTS), style,
        attrs={"seat_height_cm": rng.choice([40, 42, 44])},
        description="A conversation seat that completes the seating circle.",
    )

# --- Lighting (10) ------------------------------------------------------------------
light_specs = [
    ("Arc Floor Lamp", 40, 40, 165, (8990, 15990), "modern"),
    ("Tripod Wood Lamp", 45, 45, 150, (6990, 11990), "scandinavian"),
    ("Industrial Task Lamp", 35, 35, 145, (5990, 9990), "industrial"),
    ("Rattan Shade Lamp", 42, 42, 155, (7990, 13990), "boho"),
    ("Column Brass Lamp", 32, 32, 160, (12990, 21990), "classic"),
    ("Paper Lantern Lamp", 38, 38, 140, (3990, 6990), "minimal"),
    ("Reading Curve Lamp", 36, 36, 158, (9990, 16990), "modern"),
    ("Dome Studio Lamp", 34, 34, 148, (7490, 12490), "minimal"),
    ("Twin Shade Lamp", 44, 44, 162, (14990, 24990), "classic"),
    ("Slim Line Lamp", 30, 30, 152, (2999, 5990), "minimal"),
]
for name, w, d, h, (lo, hi), style in light_specs:
    add(
        "lighting", name, w, d, h, money(lo, hi),
        [rng.choice(["Steel", "Brass", "Wood", "Rattan"]), "Fabric Shade"],
        pick_colors(NEUTRALS[:4] + ["Brass", "Black"]), style, shape="round",
        description="Layered light beside the seating, away from walk paths.",
    )

# --- Storage (8) ----------------------------------------------------------------------
storage_specs = [
    ("Ladder Bookshelf", 70, 40, 180, (12990, 21990), "scandinavian"),
    ("Low Sideboard", 160, 42, 75, (34990, 54990), "modern"),
    ("Mesh Door Cabinet", 90, 40, 120, (24990, 39990), "industrial"),
    ("Open Cube Shelf", 120, 38, 140, (19990, 32990), "minimal"),
    ("Heritage Display Cabinet", 100, 45, 170, (49990, 89990), "classic"),
    ("Cane Door Sideboard", 140, 45, 80, (39990, 64990), "boho"),
    ("Slim Console Shelf", 80, 35, 110, (9990, 16990), "minimal"),
    ("Wide Media Bookcase", 180, 40, 160, (44990, 74990), "modern"),
]
for name, w, d, h, (lo, hi), style in storage_specs:
    add(
        "storage", name, w, d, h, money(lo, hi),
        [rng.choice(WOODS), rng.choice(["Steel", "Cane", "Veneer"])],
        pick_colors(WOODS + NEUTRALS[:2]), style,
        description="Closed and open storage to keep the room tidy.",
    )

# --- Decor (12) -------------------------------------------------------------------------
decor_specs = [
    ("Monstera Floor Plant", 45, 45, 150, (1990, 3990), "boho"),
    ("Areca Palm Planter", 40, 40, 140, (2490, 4490), "scandinavian"),
    ("Seagrass Basket Set", 38, 38, 45, (1490, 2990), "boho"),
    ("Ceramic Floor Vase", 28, 28, 70, (2990, 5990), "minimal"),
    ("Rubber Tree Plant", 42, 42, 130, (2290, 4290), "modern"),
    ("Terracotta Urn", 32, 32, 60, (3490, 6490), "classic"),
    ("Snake Plant Trio", 30, 30, 90, (1790, 3290), "minimal"),
    ("Woven Floor Lantern", 35, 35, 55, (2490, 4990), "boho"),
    ("Stone Sculpture", 25, 25, 45, (4990, 9999), "modern"),
    ("Olive Tree Planter", 48, 48, 160, (5990, 9990), "scandinavian"),
    ("Brass Floor Candle Stand", 24, 24, 80, (1990, 3790), "classic"),
    ("Dried Pampas Set", 26, 26, 95, (499, 1990), "boho"),
]
for name, w, d, h, (lo, hi), style in decor_specs:
    add(
        "decor", name, w, d, h, money(lo, hi),
        [rng.choice(["Ceramic", "Seagrass", "Terracotta", "Brass", "Live Plant"])],
        pick_colors(ACCENTS + NEUTRALS[:2]), style, shape="round",
        description="Finishing touches that make the room feel lived-in.",
    )

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(products, indent=1))
print(f"Wrote {len(products)} products to {OUT}")
for cat in PHOTOS:
    n = sum(1 for p in products if p["category"] == cat)
    lo = min(p["price"] for p in products if p["category"] == cat)
    hi = max(p["price"] for p in products if p["category"] == cat)
    print(f"  {cat:13s} {n:3d}  USD {lo:,} - USD {hi:,}")
