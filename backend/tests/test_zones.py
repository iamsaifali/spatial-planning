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


# --- side table keeps clearance from OTHER placed furniture (e.g. a chaise on a sofa flank) ---
#
# Regression for the "side table jammed against the chaise-lounge" bug: the side table steers to a
# sofa flank but must ALSO keep a furniture-clearance margin from whatever is already there. A chaise
# that clips only the OUTER part of a flank leaves enough clear area to pass the old zone area check,
# yet the deterministic anchor pose lands a couple of cm from the chaise - so the gate must reject
# that flank and use the clear one (or, if both are crowded, return nothing so the piece is skipped).

from spatial_planning.models.geometry import Door, Room, Window  # noqa: E402
from spatial_planning.models.products import Product  # noqa: E402
from spatial_planning.services.spatial.geometry_utils import (  # noqa: E402
    add,
    dot,
    item_polygon,
    sub,
    unit,
)

_CHAISE = Product(
    id="chaise-z-1", name="Chaise", brand="B", category="chaise-lounge", price=700,
    width_cm=145.0, depth_cm=85.0, height_cm=82.0, style_tags=["modern"], colors=["Grey"],
    materials=["Linen"], delivery_days=4, rating=4.2, is_walkable=False, seating_capacity=1,
)

# A room roomy enough on each sofa flank to place a chaise-lounge that only PARTIALLY clips the
# side-table rect (so the old area check still passed and the pose still jammed).
_FLANK_ROOM = Room(
    vertices=[(0, 0), (700, 0), (700, 540), (0, 540)],
    doors=[Door(id="d1", wall_index=0, offset_cm=40, width_cm=90)],
    windows=[Window(id="w1", wall_index=2, offset_cm=300, width_cm=180)],
)


def _chaise_clipping_flank(zone, sofa_item, side_table, analysis):
    """A chaise-lounge placed so it clips only the OUTER part of `zone`'s side-table rect: its inner
    edge sits ~12 cm inside where the side table's outer edge would be, leaving clear area inboard."""
    pose = anchor_pose(zone, side_table, analysis)
    outward = unit(*sub(zone.origin, (sofa_item.x, sofa_item.y)))
    cx, cy = add((pose.x, pose.y), outward, side_table.width_cm / 2.0 + _CHAISE.width_cm / 2.0 - 12.0)
    placed = PlacedItem(
        instance_id=f"chaise-{zone.anchor_label}", product_id=_CHAISE.id,
        x=cx, y=cy, rotation_deg=sofa_item.rotation_deg,
    )
    return placed, _CHAISE


def _chaise_poly(placed_chaise):
    it = placed_chaise[0]
    return item_polygon(it.x, it.y, _CHAISE.width_cm, _CHAISE.depth_cm, it.rotation_deg)


def _place_flank_sofa(catalog_repo, analysis):
    product = catalog_repo.in_category("sofa")[0]
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    pose = anchor_pose(zones[0], product, analysis)
    item = PlacedItem(instance_id="sofa-f1", product_id=product.id, x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg)
    return item, product


def test_side_table_takes_clear_flank_off_chaise(catalog_repo):
    """A chaise crowds the side table's PREFERRED flank -> the side table takes the clear flank, and
    every returned zone's realized pose clears the chaise by the furniture buffer (never ~0 cm)."""
    analysis = analyze_room(_FLANK_ROOM)
    sofa_item, sofa_product = _place_flank_sofa(catalog_repo, analysis)
    stats = catalog_repo.category_stats()
    side_table = catalog_repo.in_category("side_table")[0]

    # the flank the side table WOULD pick with nothing in the way (the preferred, top-scored zone)
    preferred = zones_for_category("side_table", analysis, [(sofa_item, sofa_product)], stats)[0]
    chaise = _chaise_clipping_flank(preferred, sofa_item, side_table, analysis)
    assert _chaise_poly(chaise).within(analysis.polygon.buffer(2.0)), "test chaise must sit inside the room"

    zones = zones_for_category("side_table", analysis, [(sofa_item, sofa_product), chaise], stats)
    assert zones, "the clear flank should still yield a side-table zone"

    cpoly = _chaise_poly(chaise)
    for z in zones:
        pose = anchor_pose(z, side_table, analysis)
        foot = item_polygon(pose.x, pose.y, side_table.width_cm, side_table.depth_cm, pose.rotation_deg)
        assert foot.distance(cpoly) >= 18.0, "side table must not be jammed against the chaise"

    # the chosen flank is the one OPPOSITE the chaise (the clear side), not the crowded preferred one
    chaise_side = dot(sub((chaise[0].x, chaise[0].y), (sofa_item.x, sofa_item.y)), sub(preferred.origin, (sofa_item.x, sofa_item.y)))
    picked_side = dot(sub(zones[0].origin, (sofa_item.x, sofa_item.y)), sub(preferred.origin, (sofa_item.x, sofa_item.y)))
    assert chaise_side > 0.0 and picked_side < 0.0, "side table should switch to the flank opposite the chaise"


def test_side_table_skipped_when_both_flanks_crowded(catalog_repo):
    """Both sofa flanks clipped by a chaise -> no clear side-table pose survives, so the generator
    returns no zone and the opt-in side table is skipped rather than jammed against a neighbour."""
    analysis = analyze_room(_FLANK_ROOM)
    sofa_item, sofa_product = _place_flank_sofa(catalog_repo, analysis)
    stats = catalog_repo.category_stats()
    side_table = catalog_repo.in_category("side_table")[0]

    both = zones_for_category("side_table", analysis, [(sofa_item, sofa_product)], stats)
    assert len(both) == 2, "both flanks should be candidate zones when nothing is in the way"
    placed = [(sofa_item, sofa_product)] + [_chaise_clipping_flank(z, sofa_item, side_table, analysis) for z in both]

    zones = zones_for_category("side_table", analysis, placed, stats)
    assert zones == [], "both flanks crowded -> the side table yields (no zone)"


def test_plant_secondary_zone_beside_the_console(catalog_repo):
    """The plant (decor/corners) gets a SECONDARY location tucked beside the console - used only when
    no empty corner survives. Verify: with a console placed, `_beside_console_spots` yields a spot that
    (a) sits BESIDE the console, (b) is scored below a real corner (so an empty corner always wins),
    and (c) actually fits inside the room."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.services.spatial.geometry_utils import item_polygon
    from spatial_planning.services.spatial.zones import _beside_console_spots

    # a room > 24 m2 so the console isn't size-skipped (small/medium rooms drop the console)
    room = Room.model_validate(
        {"vertices": [[0, 0], [600, 0], [600, 520], [0, 520]],
         "doors": [{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": 85}], "windows": []}
    )
    analysis = analyze_room(room)
    stats = catalog_repo.category_stats()
    placed = [_place_sofa(catalog_repo, analysis)]

    # place a real console on its wall (via the storage zone + anchor)
    console_prod = catalog_repo.in_category("storage")[0]
    czones = zones_for_category("storage", analysis, placed, stats)
    assert czones, "expected a console zone in a 4.8x3.6 living room"
    cpose = anchor_pose(czones[0], console_prod, analysis)
    console_item = PlacedItem(
        instance_id="console-i1", product_id=console_prod.id,
        x=cpose.x, y=cpose.y, rotation_deg=cpose.rotation_deg,
    )
    placed.append((console_item, console_prod))

    beside = _beside_console_spots(analysis, placed)
    assert beside, "expected a beside-console fallback spot next to the placed console"
    cpoly = item_polygon(cpose.x, cpose.y, console_prod.width_cm, console_prod.depth_cm, cpose.rotation_deg)
    for z in beside:
        assert z.anchor_label.startswith("beside_console")
        assert z.score < 0.7, "must rank BELOW a real corner (a genuinely empty corner wins)"
        assert z.polygon.distance(cpoly) < 30.0, "the spot must sit right beside the console"
        assert z.polygon.within(analysis.polygon.buffer(1.5)), "the spot must fit inside the room"
