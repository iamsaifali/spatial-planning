"""Deterministic product scoring: 0..100 across four weighted dimensions."""

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
    "compat": 15.0,
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


# --- preference modifiers ---------------------------------------------------------
# ADDITIVE bonus on top of the proven 0..100 base score. Gated on seating_capacity being
# supplied, so when it is absent the bonus is exactly 0 and the recommendation is unchanged.
SEATING_BONUS = 8.0


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


def preference_bonus(
    product: Product,
    prefs: Preferences,
    placed: list[PlacedProduct],
) -> tuple[float, dict[str, float | str | bool]]:
    """The additive seating-capacity modifier + explainability facts."""
    seating = _seating_bonus(product, prefs, placed)
    facts: dict[str, float | str | bool] = {}
    if seating:
        facts["pref_bonus"] = round(seating, 2)
        facts["seating_fit"] = round(seating / SEATING_BONUS, 2)
    return seating, facts


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
    cm, compat_facts = compat_score(product, placed)

    base = (
        WEIGHTS["spatial"] * sp
        + WEIGHTS["style"] * st
        + WEIGHTS["color"] * co
        + WEIGHTS["compat"] * cm
    )
    # Additive seating-capacity modifier; exactly 0 when no seat target is supplied, so
    # the default flow is unchanged. Clamp to keep the score normalised to 0..100.
    bonus, bonus_facts = preference_bonus(product, prefs, placed)
    score = max(0.0, min(100.0, base + bonus))
    facts: dict[str, float | str | bool] = {
        "zone_utilization": round(utilization, 2),
        "style_match": round(st, 2),
        **compat_facts,
        **bonus_facts,
    }
    return round(score, 2), facts
