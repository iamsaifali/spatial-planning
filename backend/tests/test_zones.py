from app.models.geometry import PlacedItem
from app.services.spatial.analyze import analyze_room
from app.services.spatial.zones import anchor_pose, fits_zone, zones_for_category


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
    from app.services.spatial.geometry_utils import item_polygon

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

    from app.models.preferences import Preferences
    from app.services.recommend.selector import select_recommendations

    result = select_recommendations("sofa", zones, Preferences(), [], catalog_repo)
    if result.recommendations:
        assert result.recommendations[0].product.width_cm < 200, "tiny room must get a compact recommendation"


def test_additional_sofa_flanks_primary_perpendicular(catalog_repo):
    """L/U scaling: the 2nd and 3rd sofas are perpendicular arms flanking the primary
    sofa's two ends, forming a tight conversation group around the open centre (not
    stranded against the far walls)."""
    from app.models.geometry import Room
    from app.services.spatial.geometry_utils import dot, sub, width_axis

    big = Room(
        vertices=[(0, 0), (700, 0), (700, 600), (0, 600)],
        doors=[{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": 90}],
    )
    analysis = analyze_room(big)
    stats = catalog_repo.category_stats()
    sofa = catalog_repo.in_category("sofa")[0]

    z1 = zones_for_category("sofa", analysis, [], stats)
    assert z1
    p1 = anchor_pose(z1[0], sofa, analysis)
    s1 = PlacedItem(instance_id="s1", product_id=sofa.id, x=p1.x, y=p1.y, rotation_deg=p1.rotation_deg)
    pw = width_axis(p1.rotation_deg)  # primary's width axis - arms sit on either side of it

    # 2nd sofa -> a perpendicular arm beside the primary
    z2 = zones_for_category("sofa", analysis, [(s1, sofa)], stats)
    assert z2, "expected an L-return arm for the 2nd sofa"
    assert 60 < abs((z2[0].rotation_deg - p1.rotation_deg) % 180) < 120, "2nd sofa not perpendicular"
    p2 = anchor_pose(z2[0], sofa, analysis)
    side2 = dot(sub((p2.x, p2.y), (p1.x, p1.y)), pw)

    # arm sits close to the primary, NOT stranded against a far wall (tight group)
    assert abs(side2) < sofa.width_cm + 200, "2nd sofa stranded too far from the primary"

    # 3rd sofa -> the OPPOSITE arm (U)
    s2 = PlacedItem(instance_id="s2", product_id=sofa.id, x=p2.x, y=p2.y, rotation_deg=p2.rotation_deg)
    z3 = zones_for_category("sofa", analysis, [(s1, sofa), (s2, sofa)], stats)
    assert z3, "expected the opposite arm for the 3rd sofa"
    assert 60 < abs((z3[0].rotation_deg - p1.rotation_deg) % 180) < 120, "3rd sofa not perpendicular"
    p3 = anchor_pose(z3[0], sofa, analysis)
    side3 = dot(sub((p3.x, p3.y), (p1.x, p1.y)), pw)
    assert side2 * side3 < 0, "3rd sofa should flank the opposite side from the 2nd"


def test_busy_room_sofa_zones_tight_or_absent(busy_room, catalog_repo):
    analysis = analyze_room(busy_room)
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    for zone in zones:
        assert zone.seg is None or (zone.seg[1] - zone.seg[0]) < 160
