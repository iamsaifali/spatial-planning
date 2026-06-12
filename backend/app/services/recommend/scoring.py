"""Deterministic product scoring: 0..100 across six weighted dimensions."""

from app.models.geometry import PlacedItem
from app.models.preferences import Preferences
from app.models.products import Product
from app.services.catalog.repository import CatalogRepository
from app.services.recommend.compat_rules import color_harmony, compat_score
from app.services.spatial.core import ZoneData
from app.services.spatial.zones import zone_utilization

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

    score = (
        WEIGHTS["spatial"] * sp
        + WEIGHTS["style"] * st
        + WEIGHTS["color"] * co
        + WEIGHTS["budget"] * bu
        + WEIGHTS["compat"] * cm
        + WEIGHTS["availability"] * av
    )
    facts: dict[str, float | str | bool] = {
        "zone_utilization": round(utilization, 2),
        "style_match": round(st, 2),
        "budget_fit": round(bu, 2),
        **compat_facts,
    }
    return round(score, 2), facts
