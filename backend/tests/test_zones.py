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


def _bedroom_product(pid, cat, w, d, seats=0, walkable=False):
    from spatial_planning.models.products import Product
    return Product(
        id=pid, name=cat.title(), brand="B", category=cat, price=400,
        width_cm=w, depth_cm=d, height_cm=75.0, style_tags=["modern"], colors=["Grey"],
        materials=[], delivery_days=5, rating=4.2, is_walkable=walkable, seating_capacity=seats,
    )


def test_work_nook_desk_on_clear_wall_and_chair_faces_it(catalog_repo):
    """The bedroom work nook: the desk hugs a clear SOLID wall that is NOT the bed's wall, and its
    chair is pulled up in FRONT of the desk, turned to face it (reuses the vanity-seat mechanism)."""
    from spatial_planning.models.geometry import PlacedItem, Room
    from spatial_planning.services.spatial.geometry_utils import dot, front_vector
    from spatial_planning.services.spatial.zones import (
        _desk_chair_zones, _desk_zones, anchor_pose,
    )

    room = Room.model_validate(
        {"vertices": [[0, 0], [400, 0], [400, 500], [0, 500]],
         "doors": [{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": 85}], "windows": []}
    )
    analysis = analyze_room(room)
    stats = catalog_repo.category_stats()

    bed = _bedroom_product("bed-z", "bed", 160.0, 200.0)
    bed_item = PlacedItem(instance_id="bed-1", product_id=bed.id, x=200.0, y=105.0, rotation_deg=0.0)
    bed_wall = max(range(len(analysis.walls)),
                   key=lambda i: dot(analysis.walls[i].normal, front_vector(bed_item.rotation_deg)))
    placed = [(bed_item, bed)]

    dzones = _desk_zones(analysis, placed, stats)
    assert dzones, "the desk should find a clear wall"
    desk = _bedroom_product("desk-z", "office-table", 140.0, 70.0)
    dpose = anchor_pose(dzones[0], desk, analysis)
    desk_wall = max(range(len(analysis.walls)),
                    key=lambda i: dot(analysis.walls[i].normal, front_vector(dpose.rotation_deg)))
    assert desk_wall != bed_wall, "the desk must avoid the bed's wall"
    desk_item = PlacedItem(instance_id="desk-1", product_id=desk.id, x=dpose.x, y=dpose.y, rotation_deg=dpose.rotation_deg)
    placed.append((desk_item, desk))

    czones = _desk_chair_zones(analysis, placed, stats)
    assert czones, "the desk chair should be placed in front of the desk"
    chair = _bedroom_product("oc-z", "office-chair", 60.0, 60.0, seats=1)
    cpose = anchor_pose(czones[0], chair, analysis)
    dfront = front_vector(dpose.rotation_deg)  # the desk faces into the room
    ahead = dot((cpose.x - desk_item.x, cpose.y - desk_item.y), dfront)
    assert ahead > 0.0, "the chair must sit in FRONT of the desk (into the room)"


def test_work_nook_desk_needs_a_desk_before_a_chair(catalog_repo):
    """No desk placed -> no work-nook chair (never orphaned)."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.services.spatial.zones import _desk_chair_zones

    room = Room.model_validate(
        {"vertices": [[0, 0], [400, 0], [400, 500], [0, 500]], "doors": [], "windows": []}
    )
    analysis = analyze_room(room)
    assert _desk_chair_zones(analysis, [], catalog_repo.category_stats()) == []


def test_work_nook_desk_clears_the_door_and_keeps_a_bed_passage(catalog_repo):
    """The work-nook desk never sits flush to a door swing, and it keeps a walkable passage off the
    bed (so it can't block the way past). Covers the door-clearance + bed-clearance fixes."""
    from shapely.ops import unary_union
    from spatial_planning.models.geometry import PlacedItem, Room
    from spatial_planning.services.spatial.geometry_utils import item_polygon
    from spatial_planning.services.spatial.zones import _desk_zones, anchor_pose

    room = Room.model_validate(
        {"vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
         "doors": [{"id": "d", "wall_index": 0, "offset_cm": 0, "width_cm": 90}], "windows": []}
    )
    analysis = analyze_room(room)
    swing = unary_union(list(analysis.swing_arcs.values()))
    bed = _bedroom_product("bed-z", "bed", 160.0, 200.0)
    bed_item = PlacedItem(instance_id="bed-1", product_id=bed.id, x=380.0, y=180.0, rotation_deg=90.0)
    bed_poly = item_polygon(bed_item.x, bed_item.y, bed.width_cm, bed.depth_cm, bed_item.rotation_deg)
    placed = [(bed_item, bed)]

    from spatial_planning.services.spatial.zones import fits_zone

    zones = _desk_zones(analysis, placed, catalog_repo.category_stats())
    assert zones, "the desk should still find a wall"
    desk = _bedroom_product("desk-z", "office-table", 100.0, 60.0)
    # The CHOSEN desk (the best zone it actually fits) must clear the door swing and keep a bed passage;
    # a too-small fallback zone is never used for this product (fits_zone / validation reject it).
    chosen = next((z for z in zones if fits_zone(z, desk)), None)
    assert chosen is not None, "the desk should fit its best wall"
    pose = anchor_pose(chosen, desk, analysis)
    poly = item_polygon(pose.x, pose.y, desk.width_cm, desk.depth_cm, pose.rotation_deg)
    assert poly.distance(swing) > 20.0, "the desk must keep clear of the door swing (not touching)"
    assert poly.distance(bed_poly) >= 40.0, "the desk must keep a walkable passage off the bed"


def test_bedroom_tv_lands_on_the_wall_the_bed_faces(catalog_repo):
    """The bedroom TV unit goes on the wall the bed FACES (opposite the headboard) - watchable from bed."""
    from spatial_planning.models.geometry import PlacedItem, Room
    from spatial_planning.services.spatial.geometry_utils import dot, front_vector
    from spatial_planning.services.spatial.zones import _bedroom_tv_zones, anchor_pose

    room = Room.model_validate(
        {"vertices": [[0, 0], [480, 0], [480, 360], [0, 360]], "doors": [], "windows": []}
    )
    analysis = analyze_room(room)
    bed = _bedroom_product("bed-z", "bed", 160.0, 200.0)
    bed_item = PlacedItem(instance_id="bed-1", product_id=bed.id, x=380.0, y=180.0, rotation_deg=90.0)
    bf = front_vector(bed_item.rotation_deg)
    bed_faces = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, (-bf[0], -bf[1])))

    zones = _bedroom_tv_zones(analysis, [(bed_item, bed)], catalog_repo.category_stats())
    assert zones, "the TV should find the facing wall"
    tv = _bedroom_product("tv-z", "tv-table", 160.0, 45.0)
    pose = anchor_pose(zones[0], tv, analysis)
    tv_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, front_vector(pose.rotation_deg)))
    assert tv_wall == bed_faces, "the TV must be on the wall the bed faces"


def test_bedroom_tv_needs_a_bed(catalog_repo):
    """No bed -> no TV (never orphaned)."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.services.spatial.zones import _bedroom_tv_zones

    room = Room.model_validate({"vertices": [[0, 0], [400, 0], [400, 400], [0, 400]], "doors": [], "windows": []})
    analysis = analyze_room(room)
    assert _bedroom_tv_zones(analysis, [], catalog_repo.category_stats()) == []


def test_bedroom_lounge_sofa_on_a_side_wall_near_the_bed_toe(catalog_repo):
    """The bedroom LOUNGE sofa hugs a SIDE wall ONLY (never the headboard wall nor the wall the bed
    faces / the TV wall), and it sits NEAR the TOE (foot) of the bed - its near edge just past the
    foot, close to it, so the sitting area is right by the toe rather than off in the far corner."""
    from spatial_planning.models.geometry import PlacedItem, Room
    from spatial_planning.services.spatial.geometry_utils import dot, front_vector
    from spatial_planning.services.spatial.zones import _lounge_sofa_zones, anchor_pose, fits_zone

    room = Room.model_validate(
        {"vertices": [[0, 0], [500, 0], [500, 600], [0, 600]],
         "doors": [{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": 85}], "windows": []}
    )
    analysis = analyze_room(room)
    bed = _bedroom_product("bed-z", "bed", 160.0, 200.0)
    bed_item = PlacedItem(instance_id="bed-1", product_id=bed.id, x=250.0, y=105.0, rotation_deg=0.0)
    bf = front_vector(bed_item.rotation_deg)
    headboard_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, bf))
    tv_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, (-bf[0], -bf[1])))
    foot_y = bed_item.y + bf[1] * bed.depth_cm / 2.0  # the bed faces +y here -> foot at larger y

    zones = _lounge_sofa_zones(analysis, [(bed_item, bed)], catalog_repo.category_stats())
    assert zones, "the lounge sofa should find a side wall"
    sofa = _bedroom_product("lounge-z", "2-seater-sofa", 190.0, 90.0, seats=2)
    chosen = next((z for z in zones if fits_zone(z, sofa)), None)
    assert chosen is not None, "the lounge sofa should fit its best side wall"
    pose = anchor_pose(chosen, sofa, analysis)
    sofa_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, front_vector(pose.rotation_deg)))
    assert sofa_wall not in (headboard_wall, tv_wall), "the lounge sofa must be on a SIDE wall only"
    # The sofa runs along the side wall (rot 90/270 -> width along y); its near edge must start past the
    # bed's foot (foot_y), not creep up alongside the bed.
    near_edge_y = pose.y - sofa.width_cm / 2.0
    assert near_edge_y >= foot_y - 2.0, "the lounge sofa must start where the bed ends (past its foot)"


def test_bedroom_lounge_sofa_needs_a_bed(catalog_repo):
    """No bed -> no lounge sofa (its placement is anchored to 'where the bed ends')."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.services.spatial.zones import _lounge_sofa_zones

    room = Room.model_validate({"vertices": [[0, 0], [500, 0], [500, 600], [0, 600]], "doors": [], "windows": []})
    analysis = analyze_room(room)
    assert _lounge_sofa_zones(analysis, [], catalog_repo.category_stats()) == []


def test_bedroom_desk_takes_the_wall_opposite_the_lounge_sofa(catalog_repo):
    """The office nook and the lounge sofa are SWAPPED (user rule): the sofa is placed FIRST and owns a
    toe-side wall, and the desk takes the OTHER side wall - never the sofa's wall, the headboard wall, or
    the TV wall (which are hard-excluded for the desk)."""
    from spatial_planning.models.geometry import PlacedItem, Room
    from spatial_planning.services.spatial.geometry_utils import dot, front_vector
    from spatial_planning.services.spatial.zones import _desk_zones, _lounge_sofa_zones, anchor_pose, fits_zone

    room = Room.model_validate(
        {"vertices": [[0, 0], [649, 0], [649, 600], [0, 600]],
         "doors": [{"id": "d", "wall_index": 0, "offset_cm": 30, "width_cm": 85}], "windows": []}
    )
    analysis = analyze_room(room)
    stats = catalog_repo.category_stats()

    def wall_of(rot):
        return max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, front_vector(rot)))

    bed = _bedroom_product("bed-z", "bed", 180.0, 210.0)
    bed_item = PlacedItem(instance_id="bed-1", product_id=bed.id, x=324.0, y=115.0, rotation_deg=0.0)
    ward = _bedroom_product("w-z", "wardrobe", 280.0, 60.0)
    ward_item = PlacedItem(instance_id="w-1", product_id=ward.id, x=32.0, y=180.0, rotation_deg=270.0)
    placed = [(bed_item, bed), (ward_item, ward)]
    headboard = wall_of(0.0)  # bed faces +y
    tv_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, (0.0, -1.0)))

    szs = _lounge_sofa_zones(analysis, placed, stats)
    assert szs, "the lounge sofa should take a side wall (placed first)"
    sofa = _bedroom_product("s-z", "2-seater-sofa", 180.0, 90.0, seats=2)
    sc = next((z for z in szs if fits_zone(z, sofa)), None)
    assert sc is not None
    sp = anchor_pose(sc, sofa, analysis)
    sofa_wall = wall_of(sp.rotation_deg)
    placed.append((PlacedItem(instance_id="s-1", product_id=sofa.id, x=sp.x, y=sp.y, rotation_deg=sp.rotation_deg), sofa))

    dzs = _desk_zones(analysis, placed, stats)
    assert dzs, "the desk should still find the opposite side wall"
    desk = _bedroom_product("d-z", "office-table", 150.0, 70.0)
    dc = next((z for z in dzs if fits_zone(z, desk)), None)
    assert dc is not None
    dp = anchor_pose(dc, desk, analysis)
    desk_wall = wall_of(dp.rotation_deg)
    assert desk_wall != sofa_wall, "the desk must take the wall OPPOSITE the lounge sofa (the swap)"
    assert desk_wall not in (headboard, tv_wall), "the desk must be on a side wall, never the headboard/TV wall"


def test_bedroom_floor_stand_sits_beside_the_lounge_sofa(catalog_repo):
    """A floor lamp (floor-stand) is placed BESIDE the lounge sofa's arm, clear of it. No lounge sofa
    placed -> no such lamp (never orphaned). Bedroom-scoped (only the bedroom recipe uses it)."""
    from spatial_planning.models.geometry import PlacedItem, Room
    from spatial_planning.services.spatial.geometry_utils import item_polygon
    from spatial_planning.services.spatial.zones import _lounge_light_zones, anchor_pose, fits_zone

    room = Room.model_validate({"vertices": [[0, 0], [500, 0], [500, 600], [0, 600]], "doors": [], "windows": []})
    analysis = analyze_room(room)
    stats = catalog_repo.category_stats()
    # No sofa -> no lounge floor stand.
    assert _lounge_light_zones(analysis, [], stats) == []

    bed = _bedroom_product("bed-z", "bed", 180.0, 210.0)
    bed_item = PlacedItem(instance_id="bed-1", product_id=bed.id, x=250.0, y=115.0, rotation_deg=0.0)
    sofa = _bedroom_product("s-z", "2-seater-sofa", 180.0, 90.0, seats=2)
    sofa_item = PlacedItem(instance_id="s-1", product_id=sofa.id, x=452.0, y=300.0, rotation_deg=90.0)
    placed = [(bed_item, bed), (sofa_item, sofa)]

    zones = _lounge_light_zones(analysis, placed, stats)
    assert zones, "the floor stand should find a spot beside the sofa"
    lamp = _bedroom_product("l-z", "floor-stand", 40.0, 40.0)
    assert fits_zone(zones[0], lamp)
    pose = anchor_pose(zones[0], lamp, analysis)
    lamp_poly = item_polygon(pose.x, pose.y, lamp.width_cm, lamp.depth_cm, pose.rotation_deg)
    sofa_poly = item_polygon(sofa_item.x, sofa_item.y, sofa.width_cm, sofa.depth_cm, sofa_item.rotation_deg)
    assert not lamp_poly.intersects(sofa_poly), "the floor stand must sit clear of the sofa, not on it"
    # beside the sofa, not marooned across the room
    from spatial_planning.services.spatial.geometry_utils import dist
    assert dist((pose.x, pose.y), (sofa_item.x, sofa_item.y)) < sofa.width_cm, "the lamp should be right beside the sofa"


def test_bedroom_center_table_sits_in_front_of_the_lounge_sofa(catalog_repo):
    """The lounge's centre table is pulled up in FRONT of the lounge sofa (into the room), not marooned."""
    from spatial_planning.models.geometry import PlacedItem, Room
    from spatial_planning.services.spatial.geometry_utils import dot, front_vector
    from spatial_planning.services.spatial.zones import _coffee_table_zones, anchor_pose

    room = Room.model_validate(
        {"vertices": [[0, 0], [500, 0], [500, 600], [0, 600]], "doors": [], "windows": []}
    )
    analysis = analyze_room(room)
    sofa = _bedroom_product("lounge-z", "2-seater-sofa", 190.0, 90.0, seats=2)
    sofa_item = PlacedItem(instance_id="lounge-1", product_id=sofa.id, x=455.0, y=300.0, rotation_deg=90.0)
    placed = [(sofa_item, sofa)]

    zones = _coffee_table_zones(analysis, placed, catalog_repo.category_stats())
    assert zones, "the centre table should sit in front of the lounge sofa"
    table = _bedroom_product("ct-z", "center-table", 110.0, 60.0)
    pose = anchor_pose(zones[0], table, analysis)
    sfront = front_vector(sofa_item.rotation_deg)
    ahead = dot((pose.x - sofa_item.x, pose.y - sofa_item.y), sfront)
    assert ahead > 0.0, "the table must sit in FRONT of the lounge sofa (into the room)"


def test_bedroom_center_table_needs_a_lounge_sofa(catalog_repo):
    """No lounge sofa placed -> no centre table (never a marooned room-centred table)."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.services.spatial.strategies import lounge_table

    room = Room.model_validate({"vertices": [[0, 0], [500, 0], [500, 600], [0, 600]], "doors": [], "windows": []})
    analysis = analyze_room(room)
    assert lounge_table("coffee_table", "bedroom", analysis, [], catalog_repo.category_stats(), {}) == []
