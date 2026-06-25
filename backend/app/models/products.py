from typing import Literal

from pydantic import Field

from app.models.geometry import StrictModel

Category = Literal[
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
]

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
