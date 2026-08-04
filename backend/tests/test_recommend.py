from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.recommend import NOTICE_NO_FIT
from spatial_planning.services.recommend.selector import select_slots
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.zones import anchor_pose, zones_for_category


def test_sofa_slots_distinct_and_ordered(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    result = select_slots("sofa", zones, Preferences(), [], catalog_repo)

    assert result.best is not None
    assert result.budget is not None
    assert result.premium is not None
    ids = {result.best.product.id, result.budget.product.id, result.premium.product.id}
    assert len(ids) == 3
    assert result.budget.product.price <= result.premium.product.price


def test_selection_deterministic(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    r1 = select_slots("sofa", zones, Preferences(), [], catalog_repo)
    r2 = select_slots("sofa", zones, Preferences(), [], catalog_repo)
    assert r1.best.product.id == r2.best.product.id
    assert r1.budget.product.id == r2.budget.product.id
    assert r1.premium.product.id == r2.premium.product.id


def test_rug_compat_facts_present(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    stats = catalog_repo.category_stats()
    sofa = catalog_repo.in_category("sofa")[0]
    sz = zones_for_category("sofa", analysis, [], stats)
    pose = anchor_pose(sz[0], sofa, analysis)
    placed = [(PlacedItem(instance_id="s1", product_id=sofa.id, x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg), sofa)]

    rug_zones = zones_for_category("rug", analysis, placed, stats)
    result = select_slots("rug", rug_zones, Preferences(), placed, catalog_repo)
    assert result.best is not None
    assert "rug_overhang_per_side_cm" in result.best.facts


def test_busy_room_no_fit_hints(busy_room, catalog_repo):
    analysis = analyze_room(busy_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    result = select_slots("sofa", zones, Preferences(), [], catalog_repo)
    if result.best is None:
        assert result.no_fit_hints.get("reason") in (NOTICE_NO_FIT, "no_zones")
        assert "smallest_in_category_cm" in result.no_fit_hints or result.no_fit_hints.get("reason") == "no_zones"
    else:
        # if anything fits it must carry the tight-fit flag
        assert "TIGHT_FIT" in result.best.notices or result.best.product.width_cm <= 160
