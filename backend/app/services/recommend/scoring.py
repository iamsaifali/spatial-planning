"""Deterministic recommendation ranking: products are RANKED by how well their
metadata (style + colour) matches the user's preferences.

Spatial fit is NOT part of the score - it is a hard gate (zones-before-products in
the selector). Budget and compatibility are no longer scored: proportional fit is
already enforced by the zone geometry, so the only ranking signal is taste. The
compat *facts* (overhang, ratios) are still computed for the 'why it fits' copy."""

from app.models.geometry import PlacedItem
from app.models.preferences import Preferences
from app.models.products import Product
from app.services.recommend.compat_rules import color_harmony, compat_score
from app.services.spatial.core import ZoneData
from app.services.spatial.zones import zone_utilization

PlacedProduct = tuple[PlacedItem, Product]

# Ranking weights over the spatially-eligible products: taste only.
WEIGHTS = {"style": 0.6, "color": 0.4}

STYLE_AFFINITY: dict[frozenset[str], float] = {
    frozenset(("scandinavian", "minimal")): 0.7,
    frozenset(("modern", "industrial")): 0.6,
    frozenset(("modern", "minimal")): 0.7,
    frozenset(("boho", "scandinavian")): 0.4,
    frozenset(("classic", "modern")): 0.3,
    frozenset(("industrial", "minimal")): 0.4,
}

NEUTRAL_COLORS = {"white", "ivory", "beige", "warm grey", "charcoal", "oat", "sand", "oak", "walnut", "teak", "black"}


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


def total_score(
    product: Product,
    zone: ZoneData,
    prefs: Preferences,
    placed: list[PlacedProduct],
) -> tuple[float, dict[str, float | str | bool]]:
    """Ranking score 0..100 from style + colour only. Spatial fit is gated upstream;
    compat facts are computed for the copy layer but do NOT affect the ranking."""
    st = style_score(product, prefs)
    co = color_score(product, prefs, placed)
    _cm, compat_facts = compat_score(product, placed)  # facts only, not scored
    utilization = zone_utilization(zone, product)

    score = 100.0 * (WEIGHTS["style"] * st + WEIGHTS["color"] * co)
    facts: dict[str, float | str | bool] = {
        "zone_utilization": round(utilization, 2),
        "style_match": round(st, 2),
        "colour_match": round(co, 2),
        **compat_facts,
    }
    return round(score, 2), facts
