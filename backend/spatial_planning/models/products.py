from typing import Literal

from pydantic import Field

from spatial_planning.models.geometry import StrictModel

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
    "chaise",  # standalone lounge placement role (chaise-lounge products; opt-in living-room piece)
    "custom",  # user's own kept items - never recommended, price 0
    # --- real multi-store categories (kept verbatim on the product; placed via PLACEMENT_GROUP) ---
    "2-seater-sofa",
    "3-seater-sofa",
    "l-shape-sofa",
    "chaise-lounge",
    "chair",
    "office-chair",
    "office-table",  # desk — placed via a work-nook rule (next phase); not yet in any recipe
    "dining-table",  # dining group — placed via a dining rule (next phase); not yet in any recipe
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
    "2-seater-sofa": "sofa", "3-seater-sofa": "sofa", "l-shape-sofa": "sofa",
    # chaise-lounge is a STANDALONE lounge piece (opt-in), NOT a sofa: its own "chaise" role so
    # the sofa role can never select it (a chaise never becomes a primary/secondary sofa).
    "chaise-lounge": "chaise",
    "chair": "accent_chair", "office-chair": "accent_chair",
    # new placement roles - no recipe uses them yet, so these products load but are not placed
    # until their rules are built (work nook / dining group). See the room-preferences plan.
    "office-table": "desk", "dining-table": "dining_table",
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
    "bedroom": {
        "side_table": "side-table",  # nightstands flanking the bed
        "storage": "wardrobe",
        "rug": "carpet",
        "accent_chair": "chair",  # a reading chair
        "lighting": "lampshade",  # a table lamp that sits ON a nightstand
    },
}


def preferred_store_category(room_type: str, role: str) -> str | None:
    """The specific store category a given room type wants for a placement role, if any."""
    return ROOM_CATEGORY_PREFERENCE.get(room_type, {}).get(role)


# Rooms below this floor area count as "small/medium": they get a 2-seater sofa (not a 3-seater)
# and no storage console - both would crowd a tight room. Rooms at/above it are "large".
SMALL_MEDIUM_MAX_CM2 = 240_000.0  # 24 m2

# Q2 main-sofa choice (Preferences.sofa_type) -> the PRIMARY sofa's STORE category. "auto" has
# no entry: the planner derives the size from room area (today's default behaviour).
SOFA_TYPE_CATEGORY: dict[str, str] = {
    "2-seater": "2-seater-sofa",
    "3-seater": "3-seater-sofa",
    "l-shape": "l-shape-sofa",
}
# Sofa size ladder, LARGEST -> smallest (by seat capacity / footprint). The primary sofa sizes
# DOWN this ladder when the chosen size can't be placed, so a room is never left sofa-less
# (honour-then-size-down). SOFA_RANK is the same order as a comparable index.
SOFA_LADDER: list[str] = ["l-shape-sofa", "3-seater-sofa", "2-seater-sofa"]
SOFA_RANK: dict[str, int] = {"2-seater-sofa": 0, "3-seater-sofa": 1, "l-shape-sofa": 2}


def seat_target_for_area(area_cm2: float) -> int:
    """Sensible seating-capacity target from room area when the user gives no explicit count.
    Shared by the planner (default target) and the accent-chair strategy (gap gate)."""
    area_m2 = area_cm2 / 10_000.0
    if area_m2 < 16.0:
        return 6  # small
    if area_m2 < 28.0:
        return 8  # medium
    return 11  # large

# "Measure the room, then shop to that size." Room-proportional MAX width (cm) per placement ROLE:
# furniture scales with the room, so a small room gets a compact piece and a large room a bigger one
# - INDEPENDENT of what (possibly oversized/mislabeled) products the catalog happens to contain.
# Anchored at 15 m2 and 30 m2, linearly interpolated by floor area, clamped to [floor, ceil]. Only
# the big wall-hugging roles need this (accents are naturally small). The selector filters candidates
# to at/under this before scoring, so the max-fill spatial score then lands on a room-appropriate
# piece instead of the biggest in the bucket - a dirty catalog can no longer oversize a room.
ROLE_WIDTH_BY_AREA: dict[str, tuple[float, float, float, float]] = {
    # role:          (@15 m2, @30 m2,  floor,  ceil)
    "sofa":          (185.0,  290.0,  150.0,  330.0),
    "tv_unit":       (170.0,  250.0,   90.0,  280.0),
    "storage":       (190.0,  290.0,   60.0,  300.0),
    "coffee_table":  (100.0,  150.0,   50.0,  160.0),
    "bed":           (155.0,  205.0,  120.0,  210.0),
}


def expected_max_width(role: str, room_area_cm2: float | None) -> float | None:
    """Room-proportional maximum width for a placement role, or None if unconstrained/unknown."""
    if room_area_cm2 is None or role not in ROLE_WIDTH_BY_AREA:
        return None
    lo, hi, floor, ceil = ROLE_WIDTH_BY_AREA[role]
    area_m2 = room_area_cm2 / 10_000.0
    w = lo + (area_m2 - 15.0) / 15.0 * (hi - lo)
    return max(floor, min(ceil, w))


def size_bounds(
    role: str, store_category: str | None, room_area_cm2: float | None
) -> tuple[float, float, float, float] | None:
    """Room-proportional (min_w, max_w, min_d, max_d) size ENVELOPE for a piece, or None if
    unconstrained. Enforces a MAX (nothing oversized - a mislabeled 4-seater in a small room) and,
    where it matters, a MIN + DEPTH bound (nothing UNDERsized - a single bed / doll-sized vanity in
    a large room). Keyed on STORE category where the storage types diverge (console/wardrobe/vanity),
    otherwise the placement ROLE. The selector filters candidates to this envelope before scoring."""
    if room_area_cm2 is None:
        return None
    t = (room_area_cm2 / 10_000.0 - 15.0) / 15.0  # 0 at 15 m2, 1 at 30 m2 (extrapolates, then clamps)
    inf = float("inf")

    def cl(lo: float, hi: float, floor: float, ceil: float) -> float:
        return max(floor, min(ceil, lo + t * (hi - lo)))

    if role == "bed":
        # width = headboard (scales with room: a large room needs at least a queen, at most a king);
        # depth = length (a bed is always ~2 m long, regardless of room size).
        return (cl(90.0, 150.0, 90.0, 150.0), cl(155.0, 210.0, 155.0, 215.0), 185.0, 215.0)
    if store_category == "dressing-table":
        # a vanity you SIT at (not a 220cm sideboard) - but it GROWS with the room so it isn't
        # doll-sized next to a full-size chair in a big bedroom: both min and max scale with area.
        return (cl(80.0, 130.0, 80.0, 130.0), cl(115.0, 160.0, 105.0, 160.0), 0.0, inf)
    if store_category == "console":
        return (100.0, 220.0, 0.0, inf)  # a media console / sideboard
    if store_category == "wardrobe":
        return (100.0, cl(190.0, 300.0, 150.0, 300.0), 0.0, inf)  # scales up with the room
    mw = expected_max_width(role, room_area_cm2)
    return (0.0, mw, 0.0, inf) if mw is not None else None

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

    # --- style / colour metadata (additive; used by preference-based matching). Free-form
    # strings (validated against app.models.style_metadata upstream, not by a Literal here) so
    # the vocabulary can grow without a schema migration. Fixture rows omit them -> empty. ---
    styles: list[str] = Field(default_factory=list)  # e.g. ["Modern", "Minimalist"]
    main_color: str = ""  # named dominant colour, e.g. "Beige"
    secondary_colors: list[str] = Field(default_factory=list)  # named accents
    main_family: str = ""  # palette family of main_color, e.g. "Warm Neutral"
    is_modular: bool = False  # can be chained along a wall (e.g. majlis benches)
    formality: Formality = "family"
    luxury_tier: LuxuryTier = "standard"
    region: Region = "global"
