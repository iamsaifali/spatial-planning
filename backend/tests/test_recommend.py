from app.models.geometry import PlacedItem
from app.models.preferences import Preferences
from app.models.recommend import NOTICE_NO_FIT
from app.services.recommend.selector import select_recommendations
from app.services.spatial.analyze import analyze_room
from app.services.spatial.zones import anchor_pose, zones_for_category


def test_recommendations_ranked_and_distinct(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    recs = select_recommendations("sofa", zones, Preferences(), [], catalog_repo).recommendations
    assert recs, "expected sofa recommendations"
    ids = [c.product.id for c in recs]
    assert len(ids) == len(set(ids)), "recommendations must be distinct"
    scores = [c.score for c in recs]
    assert scores == sorted(scores, reverse=True), "recommendations must be ranked best-first"


def test_selection_deterministic(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    r1 = select_recommendations("sofa", zones, Preferences(), [], catalog_repo)
    r2 = select_recommendations("sofa", zones, Preferences(), [], catalog_repo)
    assert [c.product.id for c in r1.recommendations] == [c.product.id for c in r2.recommendations]


def test_style_preference_ranks_matching_first(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    recs = select_recommendations("sofa", zones, Preferences(styles=["modern"]), [], catalog_repo).recommendations
    assert recs
    fitting_styles = {s for c in recs for s in c.product.style_tags}
    if "modern" in fitting_styles:  # an exact style match must outrank affinity-only picks
        assert "modern" in recs[0].product.style_tags


def test_rug_compat_facts_present(rect_room, catalog_repo):
    """Compat facts (overhang etc.) are no longer scored but are still computed for copy."""
    analysis = analyze_room(rect_room)
    stats = catalog_repo.category_stats()
    sofa = catalog_repo.in_category("sofa")[0]
    sz = zones_for_category("sofa", analysis, [], stats)
    pose = anchor_pose(sz[0], sofa, analysis)
    placed = [(PlacedItem(instance_id="s1", product_id=sofa.id, x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg), sofa)]

    rug_zones = zones_for_category("rug", analysis, placed, stats)
    recs = select_recommendations("rug", rug_zones, Preferences(), placed, catalog_repo).recommendations
    assert recs
    assert "rug_overhang_per_side_cm" in recs[0].facts


def test_busy_room_no_fit_hints(busy_room, catalog_repo):
    analysis = analyze_room(busy_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    result = select_recommendations("sofa", zones, Preferences(), [], catalog_repo)
    if not result.recommendations:
        assert result.no_fit_hints.get("reason") in (NOTICE_NO_FIT, "no_zones")
        assert "smallest_in_category_cm" in result.no_fit_hints or result.no_fit_hints.get("reason") == "no_zones"
    else:
        top = result.recommendations[0]
        assert "TIGHT_FIT" in top.notices or top.product.width_cm <= 160
