"""Recommendation selection: a spatial GATE (zones-before-products) with a relaxation
ladder decides which products are eligible, then they are RANKED by style+colour
similarity and the top N are returned. No price-based Best/Budget/Premium slots."""

from dataclasses import dataclass, field

from app.models.geometry import PlacedItem
from app.models.preferences import Preferences
from app.models.products import Product
from app.models.recommend import NOTICE_NO_FIT, NOTICE_PREORDER, NOTICE_TIGHT_FIT
from app.services.catalog.repository import CatalogRepository
from app.services.recommend.scoring import total_score
from app.services.spatial.core import ZoneData
from app.services.spatial.zones import fits_zone

PlacedProduct = tuple[PlacedItem, Product]

TOP_N = 5  # how many recommendations the sidebar shows


@dataclass
class Candidate:
    product: Product
    zone: ZoneData
    score: float
    facts: dict[str, float | str | bool]
    notices: list[str] = field(default_factory=list)


@dataclass
class RecResult:
    recommendations: list[Candidate]  # ranked best-first by style+colour
    no_fit_hints: dict[str, float | str]


def _gate(
    products: list[Product],
    zones: list[ZoneData],
    margin: float,
    include_out_of_stock: bool,
) -> list[tuple[Product, ZoneData, list[str]]]:
    out = []
    for product in products:
        if not include_out_of_stock and not product.in_stock:
            continue
        for zone in zones:
            if fits_zone(zone, product, margin=margin):
                notices = []
                if not product.in_stock:
                    notices.append(NOTICE_PREORDER)
                if margin > 1.0:
                    notices.append(NOTICE_TIGHT_FIT)
                out.append((product, zone, notices))
                break
    return out


def select_recommendations(
    category: str,
    zones: list[ZoneData],
    prefs: Preferences,
    placed: list[PlacedProduct],
    repo: CatalogRepository,
    products: list[Product] | None = None,
    exclude_ids: set[str] | None = None,
    limit: int = TOP_N,
) -> RecResult:
    products = products if products is not None else repo.in_category(category)
    if exclude_ids:
        products = [p for p in products if p.id not in exclude_ids]

    if not products:
        return RecResult([], {"reason": "empty_category"})
    if not zones:
        return RecResult([], {"reason": "no_zones"})

    # spatial gate with relaxation ladder: strict -> include out-of-stock -> tight fit
    gated: list[tuple[Product, ZoneData, list[str]]] = []
    for margin, include_oos in ((1.0, False), (1.0, True), (1.05, True)):
        gated = _gate(products, zones, margin, include_oos)
        if gated:
            break

    if not gated:
        smallest = min(products, key=lambda p: p.width_cm)
        zone_len = 0.0
        for zone in zones:
            if zone.kind == "wall_band" and zone.seg:
                zone_len = max(zone_len, zone.seg[1] - zone.seg[0])
            else:
                zone_len = max(zone_len, zone.lat_len)
        return RecResult([], {
            "reason": NOTICE_NO_FIT,
            "smallest_in_category_cm": smallest.width_cm,
            "zone_cm": round(zone_len, 0),
        })

    candidates: list[Candidate] = []
    for product, zone, notices in gated:
        score, facts = total_score(product, zone, prefs, placed)
        candidates.append(Candidate(product=product, zone=zone, score=score, facts=facts, notices=list(notices)))

    # rank by style+colour score, then deterministic tie-breakers
    candidates.sort(key=lambda c: (-c.score, c.product.price, -c.product.rating, c.product.id))
    return RecResult(recommendations=candidates[:limit], no_fit_hints={})
