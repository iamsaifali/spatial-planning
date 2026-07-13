"""Phase 2: the recommender consumes the taxonomy fields.

Signals are additive and gated on the preference being supplied, so empty
preferences must reproduce the pre-Phase-2 behaviour exactly.
"""

from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import Product
from spatial_planning.services.catalog.repository import CatalogRepository
from spatial_planning.services.recommend.scoring import preference_bonus, total_score
from spatial_planning.services.recommend.selector import select_slots
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.zones import zones_for_category


def _prod(pid: str, category: str = "sofa", **over) -> Product:
    base = dict(
        id=pid,
        name=pid,
        brand="T",
        category=category,
        price=500,
        width_cm=200.0,
        depth_cm=90.0,
        height_cm=80.0,
        style_tags=["modern"],
        colors=["Ivory"],
        materials=["Linen"],
        delivery_days=5,
        rating=4.0,
    )
    base.update(over)
    return Product(**base)


def _sofa_zone(room, repo):
    analysis = analyze_room(room)
    return analysis, zones_for_category("sofa", analysis, [], repo.category_stats())[0]


# --- backward compatibility -------------------------------------------------------


def test_empty_preferences_add_no_bonus(rect_room, catalog_repo):
    _a, zone = _sofa_zone(rect_room, catalog_repo)
    bonus, facts = preference_bonus(_prod("p"), zone, Preferences(), [], catalog_repo)
    assert bonus == 0.0 and facts == {}


def test_existing_living_room_still_returns_three_slots(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    for prefs in (Preferences(), Preferences(room_type="living_room")):
        r = select_slots("sofa", zones, prefs, [], catalog_repo)
        assert r.best and r.budget and r.premium
        assert len({r.best.product.id, r.budget.product.id, r.premium.product.id}) == 3


# --- room_type filtering + fallback -----------------------------------------------


def test_room_type_strong_filter(rect_room):
    repo = CatalogRepository([
        _prod("living", room_types=["living_room"]),
        _prod("majlis", room_types=["majlis"]),
    ])
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], repo.category_stats())

    r = select_slots("sofa", zones, Preferences(room_type="majlis"), [], repo)
    assert r.best is not None and r.best.product.id == "majlis"
    r = select_slots("sofa", zones, Preferences(room_type="living_room"), [], repo)
    assert r.best is not None and r.best.product.id == "living"


def test_room_type_falls_back_when_no_match(rect_room, catalog_repo):
    # the seed catalog has no majlis products -> must fall back, not return empty
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    r = select_slots("sofa", zones, Preferences(room_type="majlis"), [], catalog_repo)
    assert r.best is not None  # graceful fallback to the full category


def test_no_fit_does_not_crash_with_room_type(busy_room, catalog_repo):
    analysis = analyze_room(busy_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    r = select_slots("sofa", zones, Preferences(room_type="majlis", region="gcc"), [], catalog_repo)
    # may or may not fit, but must never raise and must carry a reason when empty
    if r.best is None:
        assert "reason" in r.no_fit_hints


# --- ranking signals (isolate one field at a time) --------------------------------


def _score(room, repo, product, prefs, placed=None):
    _a, zone = _sofa_zone(room, repo)
    return total_score(product, zone, prefs, placed or [], repo)[0]


def test_region_prefers_exact_then_global(rect_room, catalog_repo):
    prefs = Preferences(region="saudi_arabia")
    exact = _score(rect_room, catalog_repo, _prod("a", region="saudi_arabia"), prefs)
    glob = _score(rect_room, catalog_repo, _prod("b", region="global"), prefs)
    foreign = _score(rect_room, catalog_repo, _prod("c", region="south_asia"), prefs)
    assert exact > glob > foreign


def test_luxury_tier_affects_ranking(rect_room, catalog_repo):
    prefs = Preferences(luxury_tier="luxury")
    lux = _score(rect_room, catalog_repo, _prod("a", luxury_tier="luxury"), prefs)
    val = _score(rect_room, catalog_repo, _prod("b", luxury_tier="value"), prefs)
    assert lux > val


def test_formality_affects_ranking(rect_room, catalog_repo):
    prefs = Preferences(formality="formal")
    formal = _score(rect_room, catalog_repo, _prod("a", formality="formal"), prefs)
    casual = _score(rect_room, catalog_repo, _prod("b", formality="casual"), prefs)
    assert formal > casual


def test_materials_affect_ranking(rect_room, catalog_repo):
    prefs = Preferences(materials=["Velvet"])
    match = _score(rect_room, catalog_repo, _prod("a", materials=["Velvet", "Oak"]), prefs)
    miss = _score(rect_room, catalog_repo, _prod("b", materials=["Steel"]), prefs)
    assert match > miss


def test_seating_capacity_affects_ranking(rect_room, catalog_repo):
    prefs = Preferences(seating_capacity=3)
    three = _score(rect_room, catalog_repo, _prod("a", seating_capacity=3), prefs)
    one = _score(rect_room, catalog_repo, _prod("b", seating_capacity=1), prefs)
    over = _score(rect_room, catalog_repo, _prod("c", seating_capacity=6), prefs)
    assert three > one  # closer to target ranks higher
    assert three > over  # overshoot is damped, not over-rewarded


def test_seating_considers_placed_items(rect_room, catalog_repo):
    from spatial_planning.models.geometry import PlacedItem

    # target already met by a placed 3-seater -> no seating differentiation remains
    placed = [(PlacedItem(instance_id="s1", product_id="placed", x=0, y=0), _prod("placed", seating_capacity=3))]
    prefs = Preferences(seating_capacity=2)
    a = _score(rect_room, catalog_repo, _prod("a", seating_capacity=3), prefs, placed)
    b = _score(rect_room, catalog_repo, _prod("b", seating_capacity=1), prefs, placed)
    assert a == b  # remaining <= 0 -> seating bonus is 0 for both


def test_room_purpose_compact_living_prefers_smaller(rect_room, catalog_repo):
    # isolate the purpose modifier (total_score would also move spatial with width)
    _a, zone = _sofa_zone(rect_room, catalog_repo)
    prefs = Preferences(room_purpose="compact_living")
    narrow, _f = preference_bonus(_prod("a", width_cm=160), zone, prefs, [], catalog_repo)
    wide, _f2 = preference_bonus(_prod("b", width_cm=240), zone, prefs, [], catalog_repo)
    assert narrow > wide
