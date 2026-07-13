from spatial_planning.models.geometry import PlacedItem
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.zones import anchor_pose, fits_zone, zones_for_category


def test_sofa_zone_on_clear_wall(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    assert zones, "expected sofa zones in a 4.8x3.6 room"
    best = zones[0]
    # never inside a door swing
    for arc in analysis.swing_arcs.values():
        assert best.polygon.intersection(arc).area < 1.0
    assert best.kind == "wall_band"
    assert best.seg is not None and (best.seg[1] - best.seg[0]) >= 150


def test_sofa_anchor_pose_inside_room(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    product = catalog_repo.in_category("sofa")[0]
    pose = anchor_pose(zones[0], product, analysis)
    from spatial_planning.services.spatial.geometry_utils import item_polygon

    poly = item_polygon(pose.x, pose.y, product.width_cm, product.depth_cm, pose.rotation_deg)
    assert poly.within(analysis.polygon.buffer(1.5))


def _place_sofa(catalog_repo, analysis):
    product = catalog_repo.in_category("sofa")[0]
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    pose = anchor_pose(zones[0], product, analysis)
    item = PlacedItem(
        instance_id="sofa-i1", product_id=product.id,
        x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg,
    )
    return item, product


def test_relational_zones_after_sofa(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    placed = [_place_sofa(catalog_repo, analysis)]
    stats = catalog_repo.category_stats()

    rug_zones = zones_for_category("rug", analysis, placed, stats)
    assert rug_zones and rug_zones[0].kind == "frame"

    coffee_zones = zones_for_category("coffee_table", analysis, placed, stats)
    assert coffee_zones, "coffee table zone expected in front of sofa"

    tv_zones = zones_for_category("tv_unit", analysis, placed, stats)
    assert tv_zones
    side_zones = zones_for_category("side_table", analysis, placed, stats)
    assert len(side_zones) >= 1
    light_zones = zones_for_category("lighting", analysis, placed, stats)
    assert light_zones


def test_tiny_room_only_fits_compact_sofas(tiny_room, catalog_repo):
    analysis = analyze_room(tiny_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    big_sofas = [p for p in catalog_repo.in_category("sofa") if p.width_cm >= 200]
    assert big_sofas
    for zone in zones:
        for product in big_sofas:
            assert not fits_zone(zone, product), f"{product.id} should not fit a 2x2 m room"

    from spatial_planning.models.preferences import Preferences
    from spatial_planning.services.recommend.selector import select_slots

    result = select_slots("sofa", zones, Preferences(), [], catalog_repo)
    if result.best is not None:
        assert result.best.product.width_cm < 200, "tiny room must get a compact recommendation"


def test_busy_room_sofa_zones_tight_or_absent(busy_room, catalog_repo):
    analysis = analyze_room(busy_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    for zone in zones:
        assert zone.seg is None or (zone.seg[1] - zone.seg[0]) < 160
