"""Slot selection (Best Match / Budget / Premium) with a relaxation ladder."""

from dataclasses import dataclass, field

from app.models.geometry import PlacedItem
from app.models.preferences import Preferences
from app.models.products import (
    SMALL_MEDIUM_MAX_CM2,
    Product,
    placement_group,
    preferred_store_category,
    size_bounds,
)
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

# When no room_type is requested the recommender stays in the living-room world, so
# that adding Majlis-only products to the shared catalog cannot leak a Majlis bench
# into a generic living room. Majlis products are tagged room_types=["majlis"]; they
# only surface when prefs.room_type == "majlis".
DEFAULT_ROOM_TYPE = "living_room"


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
    room_area_cm2: float | None = None,
    store_category: str | None = None,
) -> SlotResult:
    products = repo.in_category(category)
    hints: dict[str, float | str] = {}

    if not products:
        return SlotResult(None, None, None, {"reason": "empty_category"})

    # room_type is a STRONG filter (defaulting to living_room when unset), but it never
    # eliminates all results: if no product in this category serves the requested room
    # type, fall back to the full category list so the relaxation ladder still has
    # candidates. region / luxury_tier are intentionally NOT hard-filtered here - they
    # steer ranking via scoring.preference_bonus so global/standard items remain valid.
    room_type = prefs.room_type or DEFAULT_ROOM_TYPE
    scoped = [p for p in products if room_type in p.room_types]
    if scoped:
        products = scoped

    # Per-room category preference: narrow the role to the specific STORE category this room
    # wants (e.g. living-room "sofa" -> "3-seater-sofa"). Falls back to the full role group when
    # the catalog has none of the preferred store category, so it never eliminates all results.
    # An explicit per-role store category (e.g. a role that wants "vase" specifically) overrides
    # the room's default preference for the placement group.
    pref_cat = store_category or preferred_store_category(room_type, category)
    # The default living-room sofa is a 3-seater, EXCEPT: a small/medium room gets a 2-seater,
    # and the SECOND sofa (the L-return in a big room) is a 2-seater - not another 3-seater.
    if pref_cat == "3-seater-sofa":
        small_medium = room_area_cm2 is not None and room_area_cm2 < SMALL_MEDIUM_MAX_CM2
        second_sofa = any(placement_group(pr.category) == "sofa" for _it, pr in placed)
        # compact_seating: the planner re-plans a would-be lone 3-seater as a 2-seater + chair.
        if small_medium or second_sofa or prefs.compact_seating:
            pref_cat = "2-seater-sofa"
    if pref_cat:
        preferred = [p for p in products if p.category == pref_cat]
        if preferred:
            products = preferred

    # "Measure the room, then shop to that size": keep candidates within the room-proportional size
    # ENVELOPE - a MAX so nothing is oversized (a mislabeled 4-seater in a small room), plus, where
    # it matters, a MIN + DEPTH bound so nothing is UNDERsized (a single bed / doll-sized vanity in a
    # large room). Per store category where the storage types diverge (console/wardrobe/vanity). Keep
    # all if the envelope would empty the pool - never eliminate every candidate.
    bounds = size_bounds(category, pref_cat, room_area_cm2)
    if bounds is not None:
        mnw, mxw, mnd, mxd = bounds
        within = [p for p in products if mnw <= p.width_cm <= mxw and mnd <= p.depth_cm <= mxd]
        if within:
            products = within

    # Snapshot the size-appropriate pool BEFORE the palette narrows it. A colour/style is a PREFERENCE,
    # never a reason to leave the room without the piece: if the palette-matching products don't FIT the
    # zone (e.g. "Wood/Natural" has a single 350cm rug that fits no room), we relax the palette below and
    # place a fitting off-palette piece instead of nothing.
    pool_pre_palette = list(products)

    # Style / colour PREFERENCE filtering ("filter when available"): narrow to products matching BOTH
    # the chosen style and a chosen colour family when such products exist; otherwise honour whichever
    # preference CAN be met - and when they conflict (no product is both), COLOUR wins. Colour is the
    # visually load-bearing choice, so a "Warm Neutral" request must never render a black piece just
    # because the only same-style products happen to be black (e.g. every Islamic-tagged sofa is
    # Monochrome). A preference never empties the pool (fall back to the wider set). Fixture rows carry
    # no style/main_family, so this is a no-op on the test catalog (goldens unaffected).
    styled = [p for p in products if prefs.style in p.styles] if prefs.style else None
    colored = [p for p in products if p.main_family in prefs.color_families] if prefs.color_families else None
    both = [p for p in styled if p.main_family in prefs.color_families] if (styled and colored) else None
    if both:
        products = both
    elif colored:
        products = colored  # colour beats style when they conflict
    elif styled:
        products = styled

    # In a small/medium room keep the media unit PROPORTIONAL to the sofa: a 2.5m tv-table
    # dwarfs a small-room 2-seater and wastes the wall. Cap tv candidates to the sofa's width
    # so the selector's fill-the-zone scoring picks the largest that still fits the seating.
    if category == "tv_unit" and room_area_cm2 is not None and room_area_cm2 < SMALL_MEDIUM_MAX_CM2:
        sofa_w = max(
            (pr.width_cm for it, pr in placed if placement_group(pr.category) == "sofa"),
            default=0.0,
        )
        if sofa_w > 0.0:
            capped = [p for p in products if p.width_cm <= sofa_w]
            if capped:
                products = capped

    # A dressing table must be a real vanity you can sit at, not a tiny 40cm stool. Require a
    # usable minimum width, so a too-short wall segment yields NO vanity (it moves to a longer
    # wall, or is skipped) rather than rendering a doll-sized table in a big room.
    if store_category == "dressing-table":
        real = [p for p in products if p.width_cm >= 80.0]
        if real:
            products = real

    # A small/medium bedroom gets COMPACT storage sized to the space: a wardrobe that doesn't span
    # the whole wall, and a modest dressing table (not the full-width vanity a big room can carry).
    if (
        category == "storage"
        and room_type == "bedroom"
        and room_area_cm2 is not None
        and room_area_cm2 < SMALL_MEDIUM_MAX_CM2
    ):
        cap = 95.0 if store_category == "dressing-table" else 200.0
        capped = [p for p in products if p.width_cm <= cap]
        if capped:
            products = capped

    if not zones:
        return SlotResult(None, None, None, {"reason": "no_zones"})

    # relaxation ladder: strict -> include out-of-stock -> tight fit margin. If the palette-filtered
    # pool yields NO fit, repeat the ladder on the pre-palette pool - the palette is a preference, not a
    # reason to drop the piece (a colour whose only rugs are oversized must not leave the room rug-less).
    gated: list[tuple[Product, ZoneData, list[str]]] = []
    for pool in (products, pool_pre_palette):
        for margin, include_oos in ((1.0, False), (1.0, True), (1.05, True)):
            gated = _gate(pool, zones, margin, include_oos)
            if gated:
                break
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
