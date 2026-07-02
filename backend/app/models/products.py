from typing import Literal

from pydantic import Field

from app.models.geometry import StrictModel

# PLACEMENT ROLES: the 10 functional categories the layout engine understands (recipes,
# zone generators, validation all key off these). Store categories below each map to exactly
# one of these via PLACEMENT_GROUP, so the engine places them without losing the store label.
Category = Literal[
    # --- placement roles (also valid product categories for the legacy/fixture catalog) ---
    "sofa",
    "tv_unit",
    "rug",
    "coffee_table",
    "side_table",
    "accent_chair",
    "lighting",
    "storage",
    "decor",
    "bed",  # bedroom primary sleeping (new category - own stats/terciles, no impact on others)
    "custom",  # user's own kept items - never recommended, price 0
    # --- real multi-store categories (kept verbatim on the product; placed via PLACEMENT_GROUP) ---
    "2-seater-sofa",
    "3-seater-sofa",
    "l-shape-sofa",
    "chaise-lounge",
    "chair",
    "office-chair",
    "tv-table",
    "center-table",
    "side-table",
    "service-table",
    "carpet",
    "console",
    "shelve",
    "storage-box",
    "wardrobe",
    "dressing-table",
    "wall-lighting",
    "lampshade",
    "floor-stand",
    "art-canvas",
    "decorative-hanger",
    "flower-pot-and-plant",
    "flower",
    "vase",
    "statue-and-antique",
    "wall-clock",
]

# Store category -> placement role. The 10 roles map to themselves (identity), so the legacy
# catalog is unaffected; store categories map onto the role whose geometry/placement fits.
PLACEMENT_GROUP: dict[str, str] = {
    "sofa": "sofa", "tv_unit": "tv_unit", "rug": "rug", "coffee_table": "coffee_table",
    "side_table": "side_table", "accent_chair": "accent_chair", "lighting": "lighting",
    "storage": "storage", "decor": "decor", "bed": "bed", "custom": "custom",
    "2-seater-sofa": "sofa", "3-seater-sofa": "sofa", "l-shape-sofa": "sofa", "chaise-lounge": "sofa",
    "chair": "accent_chair", "office-chair": "accent_chair",
    "tv-table": "tv_unit", "center-table": "coffee_table",
    "side-table": "side_table", "service-table": "side_table",
    "carpet": "rug",
    "console": "storage", "shelve": "storage", "storage-box": "storage",
    "wardrobe": "storage", "dressing-table": "storage",
    "wall-lighting": "lighting", "lampshade": "lighting", "floor-stand": "lighting",
    "art-canvas": "decor", "decorative-hanger": "decor", "flower-pot-and-plant": "decor",
    "flower": "decor", "vase": "decor", "statue-and-antique": "decor", "wall-clock": "decor",
}


def placement_group(category: str) -> str:
    """The placement role for a (possibly store-specific) category. Identity for the 10 roles."""
    return PLACEMENT_GROUP.get(category, category)


# Per-room-type preferred STORE category for each placement role. When planning that room the
# selector narrows a role's candidates to this exact store category (falling back to the whole
# role group only if the catalog has none), so e.g. a living room's "sofa" role is filled by a
# "3-seater-sofa", its "lighting" by a "floor-stand", etc. Roles absent here use the full group.
ROOM_CATEGORY_PREFERENCE: dict[str, dict[str, str]] = {
    "living_room": {
        "sofa": "3-seater-sofa",
        "tv_unit": "tv-table",
        "coffee_table": "center-table",
        "storage": "console",
        "lighting": "floor-stand",
        "decor": "flower-pot-and-plant",
        "side_table": "service-table",
        "rug": "carpet",
        "accent_chair": "chair",
    },
}


def preferred_store_category(room_type: str, role: str) -> str | None:
    """The specific store category a given room type wants for a placement role, if any."""
    return ROOM_CATEGORY_PREFERENCE.get(room_type, {}).get(role)

StyleTag = Literal[
    "modern",
    "scandinavian",
    "industrial",
    "boho",
    "classic",
    "minimal",
    # cultural vocabulary for Saudi / Majlis interiors (additive; existing products
    # use the tags above and continue to validate unchanged)
    "arabic",
    "saudi_traditional",
    "majlis",
    "modern_arabic",
    "luxury",
]

# --- foundational taxonomy for cultural / room-type aware recommendations ----------
# These are additive and orthogonal to `category` and `style_tags`. They are NOT used
# by the placement geometry yet (Majlis zones are still TODO); they exist so the
# catalog and recommender can start carrying the intent. See the recommendation
# architecture review for the rationale.
#
# TODO(majlis): when authoring Majlis SKUs, tag them with room_types=["majlis"],
# placement_type="perimeter"/"floor", region="saudi_arabia"/"gcc", and the
# arabic/majlis/luxury style tags (added separately to StyleTag).
RoomType = Literal["living_room", "majlis", "family_lounge", "bedroom", "dining"]
PlacementType = Literal["wall_hug", "perimeter", "floor", "center", "freestanding"]
Formality = Literal["casual", "family", "formal"]
LuxuryTier = Literal["value", "standard", "premium", "luxury"]
Region = Literal["global", "gcc", "saudi_arabia", "levant", "south_asia", "east_asia", "europe"]

CATEGORY_LABELS: dict[str, str] = {
    "sofa": "Sofa",
    "tv_unit": "TV Unit",
    "rug": "Rug",
    "coffee_table": "Coffee Table",
    "side_table": "Side Table",
    "accent_chair": "Accent Chair",
    "lighting": "Lighting",
    "storage": "Storage",
    "decor": "Decor",
    "bed": "Bed",
    "custom": "Your Item",
}


class Product(StrictModel):
    id: str
    name: str
    brand: str
    category: Category
    price: int = Field(ge=0)
    mrp: int | None = Field(default=None, ge=0)  # list price when discounted
    width_cm: float = Field(gt=0, le=1000)
    depth_cm: float = Field(gt=0, le=1000)
    height_cm: float = Field(gt=0, le=400)
    style_tags: list[StyleTag]
    colors: list[str]
    materials: list[str]
    in_stock: bool = True
    delivery_days: int = Field(ge=1, le=60)
    rating: float = Field(ge=0, le=5)
    attrs: dict[str, float] = Field(default_factory=dict)
    image_url: str = ""
    two_d_icon: str = ""  # top-down icon URL for the 2D canvas (real-catalog products)
    is_walkable: bool = False
    shape: Literal["rect", "round"] = "rect"
    description: str = ""

    # --- foundational cultural / room-type taxonomy (additive, backward compatible) ---
    # Defaults make every pre-existing catalog row valid as a generic living-room item.
    # The catalog loader (services/catalog/backfill.py) infers seating_capacity from
    # width for seating categories; non-seating items stay 0.
    room_types: list[RoomType] = Field(default_factory=lambda: ["living_room"])
    placement_type: PlacementType = "wall_hug"
    seating_capacity: int = Field(default=0, ge=0, le=20)  # seats this single SKU provides
    is_modular: bool = False  # can be chained along a wall (e.g. majlis benches)
    formality: Formality = "family"
    luxury_tier: LuxuryTier = "standard"
    region: Region = "global"
