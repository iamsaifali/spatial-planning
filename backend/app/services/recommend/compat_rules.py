"""Cross-product compatibility scoring vs already-placed items (0..1)."""

from app.models.geometry import PlacedItem
from app.models.products import Product

PlacedProduct = tuple[PlacedItem, Product]

NEUTRAL = 0.7

# Hardcoded palette families for color-harmony checks.
PALETTE_FAMILIES = {
    "warm_wood": {"oak", "walnut", "teak", "sheesham", "mango wood", "sand", "oat", "beige", "clay", "terracotta", "rust"},
    "cool_neutral": {"warm grey", "charcoal", "ivory", "black", "white", "stone"},
    "earth_green": {"olive", "forest green", "sage", "moss"},
    "warm_accent": {"mustard", "brass", "amber", "ochre"},
}


def _families(colors: list[str]) -> set[str]:
    found = set()
    for color in colors:
        c = color.lower()
        for family, members in PALETTE_FAMILIES.items():
            if c in members:
                found.add(family)
    return found


def _find(placed: list[PlacedProduct], category: str) -> Product | None:
    for _item, product in placed:
        if product.category == category:
            return product
    return None


def color_harmony(product: Product, placed: list[PlacedProduct]) -> float:
    if not placed:
        return NEUTRAL
    mine = _families(product.colors)
    theirs: set[str] = set()
    for _i, p in placed:
        theirs |= _families(p.colors)
    if not mine or not theirs:
        return NEUTRAL
    return 1.0 if mine & theirs else 0.45


def compat_score(product: Product, placed: list[PlacedProduct]) -> tuple[float, dict[str, float | str | bool]]:
    """Category-specific fit against anchors already in the room."""
    facts: dict[str, float | str | bool] = {}
    cat = product.category
    sofa = _find(placed, "sofa")
    rug = _find(placed, "rug")

    if cat == "rug" and sofa is not None:
        ideal = sofa.width_cm + 60.0
        facts["sofa_width_cm"] = sofa.width_cm
        facts["rug_overhang_per_side_cm"] = round((product.width_cm - sofa.width_cm) / 2.0, 1)
        if product.width_cm >= ideal:
            return 1.0, facts
        if product.width_cm >= sofa.width_cm:
            return 0.6, facts
        return 0.2, facts

    if cat == "coffee_table":
        score = NEUTRAL
        if sofa is not None:
            ratio = product.width_cm / sofa.width_cm
            facts["table_to_sofa_ratio"] = round(ratio, 2)
            score = 1.0 if 0.45 <= ratio <= 0.7 else (0.6 if 0.3 <= ratio <= 0.85 else 0.3)
        if rug is not None:
            fits_rug = (
                product.width_cm <= rug.width_cm - 40.0 and product.depth_cm <= rug.depth_cm - 40.0
            )
            facts["fits_on_rug"] = fits_rug
            score = min(score, 1.0 if fits_rug else 0.4)
        return score, facts

    if cat == "side_table" and sofa is not None:
        arm = sofa.attrs.get("arm_height_cm")
        if arm:
            diff = abs(product.height_cm - arm)
            facts["arm_height_delta_cm"] = round(diff, 1)
            return (1.0 if diff <= 5 else 0.6 if diff <= 12 else 0.35), facts

    if cat == "tv_unit" and sofa is not None:
        ratio = product.width_cm / sofa.width_cm
        facts["tv_to_sofa_ratio"] = round(ratio, 2)
        return (1.0 if ratio >= 0.75 else 0.55 if ratio >= 0.55 else 0.35), facts

    if cat == "accent_chair" and sofa is not None:
        seat = product.attrs.get("seat_height_cm")
        sofa_seat = sofa.attrs.get("seat_height_cm")
        if seat and sofa_seat:
            diff = abs(seat - sofa_seat)
            facts["seat_height_delta_cm"] = round(diff, 1)
            return (1.0 if diff <= 5 else 0.7), facts

    # style coherence with whatever is already in the room
    if placed:
        tags = {t for _i, p in placed for t in p.style_tags}
        if set(product.style_tags) & tags:
            return 0.9, facts
        return 0.55, facts
    return NEUTRAL, facts
