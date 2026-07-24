"""Deterministic product scoring: 0..100 across six weighted dimensions."""

from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import Product, placement_group
from spatial_planning.services.catalog.repository import CatalogRepository
from spatial_planning.services.recommend.compat_rules import color_harmony, compat_score
from spatial_planning.services.spatial.core import ZoneData
from spatial_planning.services.spatial.zones import zone_utilization

PlacedProduct = tuple[PlacedItem, Product]

WEIGHTS = {
    "spatial": 35.0,
    "style": 20.0,
    "color": 10.0,
    "budget": 15.0,
    "compat": 15.0,
    "availability": 5.0,
}

STYLE_AFFINITY: dict[frozenset[str], float] = {
    frozenset(("scandinavian", "minimal")): 0.7,
    frozenset(("modern", "industrial")): 0.6,
    frozenset(("modern", "minimal")): 0.7,
    frozenset(("boho", "scandinavian")): 0.4,
    frozenset(("classic", "modern")): 0.3,
    frozenset(("industrial", "minimal")): 0.4,
}

NEUTRAL_COLORS = {"white", "ivory", "beige", "warm grey", "charcoal", "oat", "sand", "oak", "walnut", "teak", "black"}

# Completeness weights double as budget-reservation weights per category.
ESSENTIAL_WEIGHTS = {
    "sofa": 25,
    "tv_unit": 15,
    "rug": 15,
    "coffee_table": 15,
    "lighting": 10,
    "side_table": 5,
    "accent_chair": 5,
    "storage": 5,
    "decor": 5,
}


def spatial_score(product: Product, zone: ZoneData) -> tuple[float, float]:
    """(score 0..1, utilization). Triangular curve peaking at 0.75 utilization."""
    u = zone_utilization(zone, product)
    if u > 1.02:
        return 0.0, u
    score = max(0.0, 1.0 - abs(u - 0.75) / 0.45)
    return score, u


def style_score(product: Product, prefs: Preferences) -> float:
    if not prefs.styles:
        return 0.6
    best = 0.2
    for mine in product.style_tags:
        for wanted in prefs.styles:
            if mine == wanted:
                return 1.0
            best = max(best, STYLE_AFFINITY.get(frozenset((mine, wanted)), 0.2))
    return best


def color_score(product: Product, prefs: Preferences, placed: list[PlacedProduct]) -> float:
    mine = {c.lower() for c in product.colors}
    if prefs.colors:
        wanted = {c.lower() for c in prefs.colors}
        if mine & wanted:
            return 1.0
    if mine & NEUTRAL_COLORS:
        base = 0.75
    else:
        base = 0.5
    harmony = color_harmony(product, placed)
    return min(1.0, 0.6 * base + 0.4 * harmony + (0.15 if not prefs.colors else 0.0))


def budget_score(
    product: Product,
    prefs: Preferences,
    repo: CatalogRepository,
    placed: list[PlacedProduct],
) -> float:
    t1, t2 = repo.terciles(product.category)
    tercile = 0 if product.price <= t1 else (1 if product.price <= t2 else 2)

    score = 0.7
    if prefs.budget_tier is not None:
        target = {"budget": 0, "mid": 1, "premium": 2}[prefs.budget_tier]
        score = 1.0 - 0.45 * abs(tercile - target)

    if prefs.total_budget:
        spent = sum(p.price for _i, p in placed)
        remaining = max(0, prefs.total_budget - spent)
        placed_cats = {p.category for _i, p in placed}
        open_weights = sum(w for c, w in ESSENTIAL_WEIGHTS.items() if c not in placed_cats) or 1
        reserve = remaining * ESSENTIAL_WEIGHTS.get(product.category, 5) / open_weights
        if reserve <= 0:
            score = min(score, 0.1)
        elif product.price <= reserve * 1.25:
            score = min(1.0, score + 0.15)
        elif product.price <= reserve * 2.0:
            score = min(score, 0.5)
        else:
            score = min(score, 0.15)
    return max(0.0, score)


def availability_score(product: Product) -> float:
    if not product.in_stock:
        return 0.0
    if product.delivery_days <= 7:
        return 1.0
    if product.delivery_days <= 21:
        return 0.5
    return 0.25


# --- taxonomy-aware preference modifiers ------------------------------------------
# These are ADDITIVE bonuses on top of the proven 0..100 base score. Every signal is
# gated on its preference being provided, so when a preference is absent the bonus is
# exactly 0 and the recommendation is byte-for-byte identical to before. This keeps
# existing living-room recommendations unchanged while letting room_type / region /
# seating_capacity / formality / luxury_tier / materials steer ranking when supplied.
#
# (The architecture review proposed rebalancing the six base WEIGHTS to make room for
# these dimensions; we deliberately take the lower-risk additive route here. To adopt
# the rebalanced weights later, move these into WEIGHTS and renormalise.)
SEATING_BONUS = 8.0
PURPOSE_BONUS = 6.0
FORMALITY_BONUS = 4.0
LUXURY_BONUS = 5.0
REGION_BONUS = 4.0
MATERIAL_BONUS = 5.0
PLACEMENT_BONUS = 3.0

_FORMALITY_RANK = {"casual": 0, "family": 1, "formal": 2}
_LUXURY_RANK = {"value": 0, "standard": 1, "premium": 2, "luxury": 3}

# zone.kind is one of "wall_band" | "frame" | "free"
_PLACEMENT_ZONE_COMPAT: dict[str, set[str]] = {
    "wall_hug": {"wall_band"},
    "perimeter": {"wall_band"},  # TODO(majlis): a dedicated perimeter zone kind
    "floor": {"frame", "free"},
    "center": {"frame", "free"},
    "freestanding": {"wall_band", "frame", "free"},
}


def _seating_bonus(product: Product, prefs: Preferences, placed: list[PlacedProduct]) -> float:
    """Reward seating that helps reach the target capacity; damp overshoot."""
    # The chaise-lounge is a standalone LOUNGE piece, not conversation seating - it never counts toward
    # (or is scored against) the seating target, so opting it in doesn't shrink the sofa/chair set.
    if prefs.seating_capacity is None or product.seating_capacity <= 0 or placement_group(product.category) == "chaise":
        return 0.0  # non-seating items are never penalised
    already = sum(
        p.seating_capacity for _i, p in placed
        if p.seating_capacity > 0 and placement_group(p.category) != "chaise"
    )
    remaining = prefs.seating_capacity - already
    if remaining <= 0:
        return 0.0  # target already met - don't pile on more seats
    seats = product.seating_capacity
    fill = min(seats, remaining) / remaining
    overshoot = max(0, seats - remaining)
    return SEATING_BONUS * fill / (1.0 + 0.5 * overshoot)


def _purpose_bonus(product: Product, prefs: Preferences, repo: CatalogRepository) -> float:
    rp = prefs.room_purpose
    if rp is None:
        return 0.0
    if rp == "entertaining":
        b = (0.6 if product.seating_capacity > 0 else 0.0) + (0.4 if product.formality == "formal" else 0.0)
        return PURPOSE_BONUS * min(1.0, b)
    if rp == "family":
        b = (0.6 if product.formality in ("family", "casual") else 0.0) + (0.4 if product.seating_capacity > 0 else 0.0)
        return PURPOSE_BONUS * min(1.0, b)
    if rp == "compact_living":
        # favour a smaller footprint relative to the category's own size range
        stats = repo.category_stats().get(product.category)
        if not stats or stats["max_w"] <= stats["min_w"]:
            return 0.0
        norm = (product.width_cm - stats["min_w"]) / (stats["max_w"] - stats["min_w"])
        return PURPOSE_BONUS * max(0.0, 1.0 - norm)
    if rp == "work_lounge":
        useful = {"sofa", "accent_chair", "coffee_table", "side_table", "storage", "tv_unit"}
        return PURPOSE_BONUS * 0.7 if product.category in useful else 0.0
    return 0.0


def _formality_bonus(product: Product, prefs: Preferences) -> float:
    if prefs.formality is None:
        return 0.0
    want = _FORMALITY_RANK[prefs.formality]
    have = _FORMALITY_RANK.get(product.formality, 1)
    return FORMALITY_BONUS * (1.0 - abs(want - have) / 2.0)


def _luxury_bonus(product: Product, prefs: Preferences) -> float:
    if prefs.luxury_tier is None:
        return 0.0
    want = _LUXURY_RANK[prefs.luxury_tier]
    have = _LUXURY_RANK.get(product.luxury_tier, 1)
    return LUXURY_BONUS * (1.0 - abs(want - have) / 3.0)


# Regionally adjacent origins (Saudi Arabia sits within the GCC), so a Saudi request
# also prefers GCC-tagged products and vice-versa, above generic global items.
_REGION_KIN: dict[str, set[str]] = {
    "saudi_arabia": {"gcc"},
    "gcc": {"saudi_arabia"},
}


def _region_bonus(product: Product, prefs: Preferences) -> float:
    if prefs.region is None:
        return 0.0
    if product.region == prefs.region:
        return REGION_BONUS
    if product.region in _REGION_KIN.get(prefs.region, set()):
        return REGION_BONUS * 0.75  # same regional family (e.g. saudi_arabia <-> gcc)
    if product.region == "global":
        return REGION_BONUS * 0.5  # global is a valid fallback, never eliminated
    return 0.0


def _material_bonus(product: Product, prefs: Preferences) -> float:
    if not prefs.materials:
        return 0.0
    want = {m.lower() for m in prefs.materials}
    mine = {m.lower() for m in product.materials}
    overlap = len(mine & want)
    return MATERIAL_BONUS * min(1.0, overlap / len(want)) if overlap else 0.0


def _placement_bonus(product: Product, prefs: Preferences, zone: ZoneData) -> float:
    # only meaningful once a room_type is chosen; for the default living-room flow this
    # is 0 and, even when on, it is uniform across a category's candidates (all wall_hug)
    # so it never reorders existing results.
    if prefs.room_type is None:
        return 0.0
    return PLACEMENT_BONUS if zone.kind in _PLACEMENT_ZONE_COMPAT.get(product.placement_type, set()) else 0.0


def preference_bonus(
    product: Product,
    zone: ZoneData,
    prefs: Preferences,
    placed: list[PlacedProduct],
    repo: CatalogRepository,
) -> tuple[float, dict[str, float | str | bool]]:
    """Sum of the additive taxonomy modifiers + explainability facts."""
    seating = _seating_bonus(product, prefs, placed)
    purpose = _purpose_bonus(product, prefs, repo)
    formality = _formality_bonus(product, prefs)
    luxury = _luxury_bonus(product, prefs)
    region = _region_bonus(product, prefs)
    material = _material_bonus(product, prefs)
    placement = _placement_bonus(product, prefs, zone)
    total = seating + purpose + formality + luxury + region + material + placement
    facts: dict[str, float | str | bool] = {}
    if total:
        facts["pref_bonus"] = round(total, 2)
        if seating:
            facts["seating_fit"] = round(seating / SEATING_BONUS, 2)
        if region:
            facts["region_match"] = product.region == prefs.region
        if luxury:
            facts["luxury_fit"] = round(luxury / LUXURY_BONUS, 2)
        if material:
            facts["material_match"] = round(material / MATERIAL_BONUS, 2)
    return total, facts


def total_score(
    product: Product,
    zone: ZoneData,
    prefs: Preferences,
    placed: list[PlacedProduct],
    repo: CatalogRepository,
) -> tuple[float, dict[str, float | str | bool]]:
    sp, utilization = spatial_score(product, zone)
    st = style_score(product, prefs)
    co = color_score(product, prefs, placed)
    bu = budget_score(product, prefs, repo, placed)
    cm, compat_facts = compat_score(product, placed)
    av = availability_score(product)

    base = (
        WEIGHTS["spatial"] * sp
        + WEIGHTS["style"] * st
        + WEIGHTS["color"] * co
        + WEIGHTS["budget"] * bu
        + WEIGHTS["compat"] * cm
        + WEIGHTS["availability"] * av
    )
    # Additive taxonomy modifiers; exactly 0 when no new preferences are supplied, so
    # the living-room flow is unchanged. Clamp to keep the score normalised to 0..100.
    bonus, bonus_facts = preference_bonus(product, zone, prefs, placed, repo)
    score = max(0.0, min(100.0, base + bonus))
    facts: dict[str, float | str | bool] = {
        "zone_utilization": round(utilization, 2),
        "style_match": round(st, 2),
        "budget_fit": round(bu, 2),
        **compat_facts,
        **bonus_facts,
    }
    return round(score, 2), facts
