"""Slot selection (Best Match / Budget / Premium) with a relaxation ladder."""

from dataclasses import dataclass, field

from app.models.geometry import PlacedItem
from app.models.preferences import Preferences
from app.models.products import Product
from app.models.recommend import (
    NOTICE_NO_FIT,
    NOTICE_OVER_BUDGET,
    NOTICE_PREORDER,
    NOTICE_TIGHT_FIT,
)
from app.services.catalog.repository import CatalogRepository
from app.services.recommend.scoring import total_score
from app.services.spatial.core import ZoneData
from app.services.spatial.zones import fits_zone

PlacedProduct = tuple[PlacedItem, Product]


@dataclass
class Candidate:
    product: Product
    zone: ZoneData
    score: float
    facts: dict[str, float | str | bool]
    notices: list[str] = field(default_factory=list)


@dataclass
class SlotResult:
    best: Candidate | None
    budget: Candidate | None
    premium: Candidate | None
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


def select_slots(
    category: str,
    zones: list[ZoneData],
    prefs: Preferences,
    placed: list[PlacedProduct],
    repo: CatalogRepository,
) -> SlotResult:
    products = repo.in_category(category)
    hints: dict[str, float | str] = {}

    if not products:
        return SlotResult(None, None, None, {"reason": "empty_category"})
    if not zones:
        return SlotResult(None, None, None, {"reason": "no_zones"})

    # relaxation ladder: strict -> include out-of-stock -> tight fit margin
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
        hints = {
            "reason": NOTICE_NO_FIT,
            "smallest_in_category_cm": smallest.width_cm,
            "zone_cm": round(zone_len, 0),
        }
        return SlotResult(None, None, None, hints)

    candidates: list[Candidate] = []
    for product, zone, notices in gated:
        score, facts = total_score(product, zone, prefs, placed, repo)
        candidates.append(Candidate(product=product, zone=zone, score=score, facts=facts, notices=list(notices)))

    # deterministic ordering: score desc, then price asc, rating desc, id
    candidates.sort(key=lambda c: (-c.score, c.product.price, -c.product.rating, c.product.id))
    best = candidates[0]

    threshold = 0.55 * best.score
    affordable = [c for c in candidates if c.score >= threshold and c.product.id != best.product.id]
    budget = min(affordable, key=lambda c: (c.product.price, c.product.id), default=None)
    if budget is None:
        # relax: cheapest of all remaining candidates, flagged
        rest = [c for c in candidates if c.product.id != best.product.id]
        budget = min(rest, key=lambda c: (c.product.price, c.product.id), default=None)
        if budget is not None:
            budget.notices.append(NOTICE_OVER_BUDGET)

    premium_pool = [
        c
        for c in candidates
        if c.score >= 0.5 * best.score
        and c.product.rating >= 4.0
        and c.product.id not in {best.product.id, budget.product.id if budget else ""}
    ]
    premium = max(premium_pool, key=lambda c: (c.product.price, c.product.rating, c.product.id), default=None)
    if premium is None:
        rest = [
            c for c in candidates
            if c.product.id not in {best.product.id, budget.product.id if budget else ""}
        ]
        premium = max(rest, key=lambda c: (c.product.price, c.product.id), default=None)

    return SlotResult(best=best, budget=budget, premium=premium, no_fit_hints=hints)
