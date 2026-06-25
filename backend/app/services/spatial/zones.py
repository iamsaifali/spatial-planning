"""Per-category placement-zone generation.

Two zone families:
- wall-band zones: rectangles along clear wall segments (sofa, tv_unit, storage)
- frame zones: rectangles anchored to an already-placed item, usually the sofa
  (rug, coffee table, side tables, accent chair) or to room corners (lighting,
  decor).

Every zone carries reason_codes — machine-readable facts the copy layer may
phrase but never extend.
"""

import math
from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.ops import unary_union

from app.models.geometry import PlacedItem, Pose
from app.models.products import Product
from app.services.spatial.core import RoomAnalysis, WallData, ZoneData
from app.services.spatial.geometry_utils import (
    Vec,
    add,
    dist,
    dot,
    extent_along,
    first_boundary_hit,
    front_vector,
    item_polygon,
    largest_piece,
    pieces_of,
    quad,
    rotate_vec,
    rotation_for_normal,
    unit,
    width_axis,
)

# reason codes
R_LONGEST_CLEAR_WALL = "longest_clear_wall"
R_KEEPS_ENTRY_OPEN = "keeps_entry_path_open"
R_FACES_FOCAL = "faces_focal_wall"
R_NEAR_WINDOW = "near_window"
R_TIGHT_SPACE = "tight_space"
R_FACES_SOFA = "faces_sofa"
R_IDEAL_VIEWING_DIST = "ideal_viewing_distance"
R_ANCHORS_SEATING = "anchors_seating_zone"
R_FRONT_LEGS_ON_RUG = "front_legs_on_rug"
R_EASY_REACH = "within_easy_reach"
R_CONVERSATION_ANGLE = "conversation_angle"
R_CORNER_LIGHT = "corner_near_seating"
R_REMAINING_WALL = "uses_remaining_wall"
R_FLEXIBLE_SPOT = "flexible_spot"
# Majlis-specific (perimeter seating)
R_MAJLIS_PERIMETER_SEATING = "majlis_perimeter_seating"
R_LONG_CLEAR_WALL = "long_clear_wall"
R_KEEP_CENTER_OPEN = "keep_center_open"
R_MAXIMIZE_SEATING = "maximize_seating"
# Bedroom
R_HEADBOARD_TO_WALL = "headboard_to_wall"
# Composition (large rooms)
R_SECONDARY_ZONE = "secondary_zone"

CategoryStats = dict[str, dict[str, float]]
PlacedProduct = tuple[PlacedItem, Product]


def _find_placed(placed: list[PlacedProduct], category: str) -> PlacedProduct | None:
    for item, product in placed:
        if product.category == category:
            return item, product
    return None


def _placed_blockers(placed: list[PlacedProduct], buffer_cm: float = 5.0):
    polys = [
        item_polygon(i.x, i.y, p.width_cm, p.depth_cm, i.rotation_deg).buffer(buffer_cm)
        for i, p in placed
        if not p.is_walkable
    ]
    return unary_union(polys) if polys else Polygon()


def _corridor_overlap_ratio(analysis: RoomAnalysis, poly: Polygon) -> float:
    if not analysis.corridors or poly.is_empty:
        return 0.0
    union = unary_union([c.polygon for c in analysis.corridors])
    return poly.intersection(union).area / max(poly.area, 1e-9)


def _window_overlap_ratio(wall: WallData, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    total = 0.0
    for op in wall.openings:
        if op.kind != "window":
            continue
        total += max(0.0, min(hi, op.b) - max(lo, op.a))
    return total / (hi - lo)


def _entry_distance_norm(analysis: RoomAnalysis, poly: Polygon) -> float:
    if not analysis.entries:
        return 0.7
    c = poly.centroid
    d = min(dist((c.x, c.y), e.point) for e in analysis.entries)
    return min(1.0, d / max(analysis.diag_cm * 0.5, 1.0))


@dataclass
class _BandCandidate:
    wall: WallData
    lo: float
    hi: float
    piece: Polygon
    extent: float


def _wall_band_candidates(
    analysis: RoomAnalysis,
    depth: float,
    min_len: float,
    use_solid: bool,
    blockers,
) -> list[_BandCandidate]:
    out: list[_BandCandidate] = []
    for wall in analysis.walls:
        segs = wall.clear_solid if use_solid else wall.clear_floor
        for a, b in segs:
            if b - a < min_len:
                continue
            band = quad(
                add(wall.point_at(a), wall.normal, 2.0),
                add(wall.point_at(b), wall.normal, 2.0),
                add(wall.point_at(b), wall.normal, 2.0 + depth),
                add(wall.point_at(a), wall.normal, 2.0 + depth),
            )
            clipped = band.intersection(analysis.polygon).difference(analysis.keep_clear_union)
            if blockers is not None and not blockers.is_empty:
                clipped = clipped.difference(blockers)
            for piece in pieces_of(clipped):
                lo, hi = extent_along(piece, wall.start, wall.dir)
                extent = hi - lo
                if extent < min_len:
                    continue
                if piece.area < extent * depth * 0.45:
                    continue
                out.append(_BandCandidate(wall=wall, lo=lo, hi=hi, piece=piece, extent=extent))
    return out


def _band_zone(
    analysis: RoomAnalysis,
    cand: _BandCandidate,
    category: str,
    idx: int,
    score: float,
    reasons: list[str],
    depth: float,
) -> ZoneData:
    return ZoneData(
        id=f"z-{category}-{idx}",
        category=category,
        polygon=cand.piece,
        score=round(score, 3),
        rotation_deg=rotation_for_normal(cand.wall.normal),
        anchor_label=f"wall_{cand.wall.index}",
        reason_codes=reasons,
        kind="wall_band",
        wall_index=cand.wall.index,
        seg=(cand.lo, cand.hi),
        band_depth=depth,
    )


def _rank(zones: list[ZoneData], limit: int = 3) -> list[ZoneData]:
    zones.sort(key=lambda z: (-z.score, z.id))
    for i, z in enumerate(zones):
        z.rank = i
    return zones[:limit]


# --- per-category generators -------------------------------------------------


def _sofa_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    s = stats.get("sofa", {})
    depth = s.get("max_d", 105.0) + 10.0
    min_w = s.get("min_w", 160.0)
    blockers = _placed_blockers(placed)

    cands = _wall_band_candidates(analysis, depth, min_w * 0.95, use_solid=False, blockers=blockers)
    tight = False
    if not cands:
        cands = _wall_band_candidates(analysis, depth, 80.0, use_solid=False, blockers=blockers)
        tight = True
    if not cands:
        return []

    max_extent = max(c.extent for c in cands)
    zones: list[ZoneData] = []
    for i, cand in enumerate(cands):
        win_ratio = _window_overlap_ratio(cand.wall, cand.lo, cand.hi)
        entry_norm = _entry_distance_norm(analysis, cand.piece)
        corridor_ratio = _corridor_overlap_ratio(analysis, cand.piece)
        focal = 0.0
        if analysis.focal_wall_index is not None:
            focal_wall = analysis.walls[analysis.focal_wall_index]
            if dot(cand.wall.normal, focal_wall.normal) < -0.5:
                focal = 1.0
        score = (
            0.40 * (cand.extent / max_extent)
            + 0.20 * (1.0 - 0.5 * win_ratio)
            + 0.20 * entry_norm
            + 0.20 * focal
            - 0.15 * corridor_ratio
        )
        reasons = []
        if cand.wall.is_longest_clear:
            reasons.append(R_LONGEST_CLEAR_WALL)
        if corridor_ratio < 0.05:
            reasons.append(R_KEEPS_ENTRY_OPEN)
        if focal:
            reasons.append(R_FACES_FOCAL)
        if win_ratio > 0.2:
            reasons.append(R_NEAR_WINDOW)
        if tight:
            reasons.append(R_TIGHT_SPACE)
        zones.append(_band_zone(analysis, cand, "sofa", i, score, reasons, depth))
    return _rank(zones)


def _tv_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    s = stats.get("tv_unit", {})
    depth = s.get("max_d", 48.0) + 8.0
    min_w = s.get("min_w", 120.0)
    sofa = _find_placed(placed, "sofa")
    blockers = _placed_blockers(placed)

    cands = _wall_band_candidates(analysis, depth, min_w * 0.95, use_solid=True, blockers=blockers)
    if not cands:
        cands = _wall_band_candidates(analysis, depth, 90.0, use_solid=True, blockers=blockers)
    if not cands:
        return []

    max_extent = max(c.extent for c in cands)
    zones: list[ZoneData] = []
    if sofa is None:
        for i, cand in enumerate(cands):
            score = 0.6 * (cand.extent / max_extent) + 0.4 * _entry_distance_norm(analysis, cand.piece)
            zones.append(_band_zone(analysis, cand, "tv_unit", i, score, [R_REMAINING_WALL], depth))
        return _rank(zones)

    item, product = sofa
    f = front_vector(item.rotation_deg)
    sofa_front = add((item.x, item.y), f, product.depth_cm / 2.0)
    for i, cand in enumerate(cands):
        facing = dot(cand.wall.normal, f) < -0.7
        # distance from sofa front to this wall along the sofa's facing direction
        d_wall = first_boundary_hit(analysis.polygon, sofa_front, f) if facing else 9999.0
        if 250.0 <= d_wall <= 400.0:
            dist_score = 1.0
        elif 150.0 <= d_wall <= 600.0:
            dist_score = 0.6
        else:
            dist_score = 0.2
        # sofa center should project inside the segment for a centered TV
        proj = dot(sub2(sofa_front, cand.wall.start), cand.wall.dir)
        span_ok = cand.lo - 40.0 <= proj <= cand.hi + 40.0
        score = (
            0.45 * (1.0 if facing and span_ok else (0.4 if facing else 0.1))
            + 0.35 * dist_score
            + 0.20 * (cand.extent / max_extent)
        )
        reasons = []
        if facing and span_ok:
            reasons.append(R_FACES_SOFA)
        if facing and 250.0 <= d_wall <= 400.0:
            reasons.append(R_IDEAL_VIEWING_DIST)
        zones.append(_band_zone(analysis, cand, "tv_unit", i, score, reasons, depth))
    return _rank(zones)


def sub2(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def _frame_zone(
    category: str,
    idx: int,
    polygon: Polygon,
    score: float,
    rotation: float,
    origin: Vec,
    fwd: Vec,
    lat: Vec,
    fwd_len: float,
    lat_len: float,
    reasons: list[str],
    anchor_label: str,
    kind: str = "frame",
) -> ZoneData:
    return ZoneData(
        id=f"z-{category}-{idx}",
        category=category,
        polygon=polygon,
        score=round(score, 3),
        rotation_deg=rotation,
        anchor_label=anchor_label,
        reason_codes=reasons,
        kind=kind,
        origin=origin,
        fwd=fwd,
        lat=lat,
        fwd_len=fwd_len,
        lat_len=lat_len,
    )


def _free_zone_center(analysis: RoomAnalysis, category: str, size_w: float, size_d: float) -> list[ZoneData]:
    """Fallback when the anchoring item is missing: a central free zone."""
    usable = largest_piece(analysis.usable_area)
    if usable is None:
        return []
    c = usable.centroid
    rect = item_polygon(c.x, c.y, size_w, size_d, 0).intersection(usable)
    piece = largest_piece(rect)
    if piece is None or piece.area < 2_000.0:
        return []
    return [
        _frame_zone(
            category, 0, piece, 0.6, 0.0, (c.x, c.y), (0.0, 1.0), (1.0, 0.0),
            size_d, size_w, [R_FLEXIBLE_SPOT], "room_center", kind="free",
        )
    ]


# Composition thresholds. Below the area threshold a room gets NO secondary zone, so
# normal rooms (and the goldens) are byte-for-byte unchanged. Only genuinely large rooms
# - where one seating group leaves an obvious empty area - compose a second cluster.
SECONDARY_ZONE_MIN_AREA_CM2 = 260_000.0  # 26 m2 of room
SECONDARY_ZONE_MIN_OPEN_CM2 = 55_000.0  # 5.5 m2 of contiguous open floor left over
SECONDARY_ZONE_TWO_CHAIR_CM2 = 75_000.0  # open area above which we seat two chairs


def _avg_dim(stats: CategoryStats, category: str, axis: str, fallback: float) -> float:
    s = stats.get(category, {})
    lo, hi = s.get(f"min_{axis}"), s.get(f"max_{axis}")
    return (lo + hi) / 2.0 if lo is not None and hi is not None else fallback


def secondary_nook_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """Compose a secondary seating cluster for a LARGE room.

    The primary recipe builds one seating group against a wall; in a big room that
    leaves a large empty area. This finds the largest open region left over and lays out
    a coherent reading/conversation nook there - a side table flanked by one or two
    accent chairs that FACE the primary group (so the two zones read as one composed
    room), plus a floor lamp. Returns 'free' zones; the interpreter selects products and
    runs each through the validation gate. Empty list for normal rooms (room below the
    area threshold, or no big-enough open region) - so smaller rooms are untouched.
    """
    if analysis.area_cm2 < SECONDARY_ZONE_MIN_AREA_CM2:
        return []
    # generous halo around existing furniture: keeps a composed nook clear of the primary
    # group AND well-separated from any earlier nook (so multiple nooks don't bunch up).
    free = analysis.usable_area.difference(_placed_blockers(placed, buffer_cm=48.0))

    # Keep the primary sofa->focus sightline clear: carve the viewing lane (the strip the
    # sofa looks down) out of the candidate area, so the secondary cluster always lands to
    # the SIDE - never between the sofa and the TV.
    sofa = _find_placed(placed, "sofa")
    if sofa is not None:
        item, prod = sofa
        f = front_vector(item.rotation_deg)
        lane_len = analysis.diag_cm
        lane_center = (item.x + f[0] * lane_len / 2.0, item.y + f[1] * lane_len / 2.0)
        lane = item_polygon(lane_center[0], lane_center[1], prod.width_cm + 70.0, lane_len, item.rotation_deg)
        free = free.difference(lane)

    region = largest_piece(free)
    if region is None or region.area < SECONDARY_ZONE_MIN_OPEN_CM2:
        return []

    ctr = region.centroid
    center = (ctr.x, ctr.y) if region.contains(ctr) else (region.representative_point().x, region.representative_point().y)
    cx, cy = center

    # Orient the pair along the open region's LONG axis, so two chairs facing each other
    # across the table fit the space (and read as a deliberate vignette, not a far aim).
    mrr_coords = list(region.minimum_rotated_rectangle.exterior.coords)
    e1 = (mrr_coords[1][0] - mrr_coords[0][0], mrr_coords[1][1] - mrr_coords[0][1])
    e2 = (mrr_coords[2][0] - mrr_coords[1][0], mrr_coords[2][1] - mrr_coords[1][1])
    long_edge = e1 if (e1[0] ** 2 + e1[1] ** 2) >= (e2[0] ** 2 + e2[1] ** 2) else e2
    u = unit(*long_edge)  # chair-pair axis (chairs sit at center +/- u*spread)
    lat = (-u[1], u[0])  # perpendicular - the lamp sits off to this side

    chair_w = _avg_dim(stats, "accent_chair", "w", 70.0)
    chair_d = _avg_dim(stats, "accent_chair", "d", 72.0)
    table_w = _avg_dim(stats, "side_table", "w", 50.0)
    lamp_w = _avg_dim(stats, "lighting", "w", 40.0)

    rot_a = rotation_for_normal(u)  # chair facing +u (toward the table)
    rot_b = rotation_for_normal((-u[0], -u[1]))  # chair facing -u
    spread = chair_d / 2.0 + table_w / 2.0 + 16.0  # table between the two facing chairs
    two_chairs = region.area >= SECONDARY_ZONE_TWO_CHAIR_CM2

    # (category, center, (w, d), rotation) - the interpreter places at center w/ rotation
    slots: list[tuple[str, Vec, tuple[float, float], float]] = [
        ("side_table", center, (table_w, table_w), rot_a),
        ("accent_chair", add(center, u, -spread), (chair_w, chair_d), rot_a),
    ]
    if two_chairs:
        slots.append(("accent_chair", add(center, u, spread), (chair_w, chair_d), rot_b))
    # floor lamp beside the vignette (perpendicular to the pair axis)
    slots.append(("lighting", add(center, lat, table_w / 2.0 + lamp_w / 2.0 + 34.0), (lamp_w, lamp_w), rot_a))

    zones: list[ZoneData] = []
    for i, (cat, (px, py), (w, d), rot) in enumerate(slots):
        poly = largest_piece(
            item_polygon(px, py, w, d, rot).intersection(analysis.polygon).difference(analysis.keep_clear_union)
        )
        if poly is None or poly.area < w * d * 0.5:
            continue  # not enough clear floor here - drop this slot, keep the rest
        zones.append(
            ZoneData(
                id=f"z2-{cat}-{i}", category=cat, polygon=poly, score=0.7, rotation_deg=rot,
                anchor_label="secondary_zone", reason_codes=[R_SECONDARY_ZONE], kind="free",
                origin=(px, py), fwd=u, lat=lat, fwd_len=d, lat_len=w,
            )
        )
    return zones


def _rug_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    s = stats.get("rug", {})
    sofa = _find_placed(placed, "sofa")
    if sofa is None:
        return _free_zone_center(analysis, "rug", s.get("max_w", 300.0), s.get("max_d", 240.0))

    item, product = sofa
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    sofa_front = add((item.x, item.y), f, product.depth_cm / 2.0)
    near = add(sofa_front, f, -25.0)  # rug slides 25 cm under the sofa front
    forward_clear = first_boundary_hit(analysis.polygon, sofa_front, f)
    fwd_len = min(forward_clear - 30.0, 260.0)
    if fwd_len < 80.0:
        fwd_len = max(forward_clear - 10.0, 60.0)
    lat_len = product.width_cm + 70.0

    inner = analysis.polygon.buffer(-12.0)
    rect = quad(
        add(near, w, -lat_len / 2.0),
        add(near, w, lat_len / 2.0),
        add(add(near, w, lat_len / 2.0), f, fwd_len),
        add(add(near, w, -lat_len / 2.0), f, fwd_len),
    )
    piece = largest_piece(rect.intersection(inner if not inner.is_empty else analysis.polygon))
    if piece is None or piece.area < 5_000.0:
        return []
    return [
        _frame_zone(
            "rug", 0, piece, 0.9, item.rotation_deg, near, f, w, fwd_len, lat_len,
            [R_FRONT_LEGS_ON_RUG, R_ANCHORS_SEATING], "sofa_front",
        )
    ]


def _coffee_table_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    if sofa is None:
        return _free_zone_center(analysis, "coffee_table", 160.0, 140.0)

    item, product = sofa
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    sofa_front = add((item.x, item.y), f, product.depth_cm / 2.0)
    origin = add(sofa_front, f, 40.0)
    fwd_len = 75.0  # table near edge sits 40..115 cm from the sofa
    lat_len = max(product.width_cm - 60.0, 70.0)

    rect = quad(
        add(origin, w, -lat_len / 2.0),
        add(origin, w, lat_len / 2.0),
        add(add(origin, w, lat_len / 2.0), f, fwd_len),
        add(add(origin, w, -lat_len / 2.0), f, fwd_len),
    )
    clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union)
    piece = largest_piece(clipped)
    if piece is None or piece.area < 3_000.0:
        return []
    rug = _find_placed(placed, "rug")
    reasons = [R_EASY_REACH]
    if rug is not None:
        reasons.append(R_ANCHORS_SEATING)
    return [
        _frame_zone(
            "coffee_table", 0, piece, 0.9, item.rotation_deg, origin, f, w, fwd_len, lat_len,
            reasons, "sofa_front",
        )
    ]


def _side_table_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    if sofa is None:
        return _corner_spots(analysis, placed, "side_table", 70.0, max_zones=2)

    item, product = sofa
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    blockers = _placed_blockers(placed)
    zones: list[ZoneData] = []
    for idx, side in enumerate((-1.0, 1.0)):
        origin = add((item.x, item.y), w, side * (product.width_cm / 2.0 + 4.0))
        rect = item_polygon(*add(origin, w, side * 35.0), 78.0, max(product.depth_cm, 80.0), item.rotation_deg)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        piece = largest_piece(clipped)
        if piece is None or piece.area < 1_500.0:
            continue
        zones.append(
            _frame_zone(
                "side_table", idx, piece, 0.85 if side < 0 else 0.84, item.rotation_deg,
                origin, (w[0] * side, w[1] * side), f, 80.0, 80.0,
                [R_EASY_REACH], f"sofa_{'left' if side < 0 else 'right'}", kind="side",
            )
        )
    return _rank(zones, limit=2)


def _accent_chair_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    if sofa is None:
        return _corner_spots(analysis, placed, "accent_chair", 110.0, max_zones=2)

    item, product = sofa
    f = front_vector(item.rotation_deg)
    seat_anchor = add((item.x, item.y), f, product.depth_cm / 2.0 + 60.0)
    blockers = _placed_blockers(placed)
    zones: list[ZoneData] = []
    for idx, ang in enumerate((-55.0, 55.0)):
        g = rotate_vec(f, ang)
        center = add(seat_anchor, g, 170.0)
        rotation = rotation_for_normal(unit(*sub2(seat_anchor, center)))
        rect = item_polygon(center[0], center[1], 120.0, 120.0, rotation)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        piece = largest_piece(clipped)
        if piece is None or piece.area < 4_000.0:
            continue
        corridor_pen = _corridor_overlap_ratio(analysis, piece)
        zones.append(
            _frame_zone(
                "accent_chair", idx, piece, 0.8 - 0.2 * corridor_pen, rotation,
                center, unit(*sub2(seat_anchor, center)), g, 110.0, 110.0,
                [R_CONVERSATION_ANGLE], "beside_seating", kind="free",
            )
        )
    return _rank(zones, limit=2)


def _corner_spots(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    category: str,
    size: float,
    max_zones: int = 3,
    near: Vec | None = None,
    near_radius: float = 0.0,
    reasons: list[str] | None = None,
) -> list[ZoneData]:
    blockers = _placed_blockers(placed, buffer_cm=8.0)
    n_v = len(analysis.room.vertices)
    spots: list[tuple[Vec, str]] = []
    for i in range(n_v):
        prev_wall = analysis.walls[(i - 1) % n_v]
        next_wall = analysis.walls[i]
        diag = unit(
            prev_wall.normal[0] + next_wall.normal[0],
            prev_wall.normal[1] + next_wall.normal[1],
        )
        if diag == (0.0, 0.0):
            continue
        corner = analysis.room.vertices[i]
        spots.append((add(corner, diag, size / 2.0 + 12.0), f"corner_{i}"))

    zones: list[ZoneData] = []
    for idx, (pt, label) in enumerate(spots):
        if near is not None and near_radius > 0 and dist(pt, near) > near_radius:
            continue
        rect = item_polygon(pt[0], pt[1], size, size, 0)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        piece = largest_piece(clipped)
        if piece is None or piece.area < size * size * 0.35:
            continue
        score = 0.7
        if near is not None:
            score = 0.7 + 0.3 * (1.0 - min(1.0, dist(pt, near) / max(near_radius, 1.0)))
        zones.append(
            _frame_zone(
                category, idx, piece, score, 0.0, pt, (0.0, 1.0), (1.0, 0.0),
                size, size, reasons or [R_FLEXIBLE_SPOT], label, kind="free",
            )
        )
    return _rank(zones, limit=max_zones)


def _lighting_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    near = None
    radius = 0.0
    if sofa is not None:
        item, product = sofa
        f = front_vector(item.rotation_deg)
        near = add((item.x, item.y), f, product.depth_cm / 2.0)
        radius = 320.0
    zones = _corner_spots(
        analysis, placed, "lighting", 55.0, max_zones=3,
        near=near, near_radius=radius, reasons=[R_CORNER_LIGHT],
    )
    if not zones:
        zones = _corner_spots(analysis, placed, "lighting", 55.0, max_zones=3, reasons=[R_CORNER_LIGHT])
    return zones


def _storage_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    s = stats.get("storage", {})
    depth = s.get("max_d", 45.0) + 6.0
    min_w = min(s.get("min_w", 80.0), 80.0)
    blockers = _placed_blockers(placed)
    cands = _wall_band_candidates(analysis, depth, min_w, use_solid=True, blockers=blockers)
    if not cands:
        return []
    max_extent = max(c.extent for c in cands)
    zones = [
        _band_zone(
            analysis, cand, "storage", i,
            0.7 * (cand.extent / max_extent) + 0.3 * _entry_distance_norm(analysis, cand.piece),
            [R_REMAINING_WALL], depth,
        )
        for i, cand in enumerate(cands)
    ]
    return _rank(zones)


def _decor_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    near = (sofa[0].x, sofa[0].y) if sofa is not None else None
    return _corner_spots(
        analysis, placed, "decor", 60.0, max_zones=4,
        near=near, near_radius=500.0 if near else 0.0, reasons=[R_FLEXIBLE_SPOT],
    )


def _bed_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """The bed against a clear wall, headboard to the wall (front faces the room).

    Reuses the wall-band machinery (like _sofa_zones) but scores for a restful bedroom:
    longest clear wall, away from windows, entry kept open. No focal/TV scoring.
    """
    s = stats.get("bed", {})
    depth = s.get("max_d", 210.0) + 10.0
    min_w = s.get("min_w", 140.0)
    blockers = _placed_blockers(placed)

    cands = _wall_band_candidates(analysis, depth, min_w * 0.95, use_solid=False, blockers=blockers)
    tight = False
    if not cands:
        cands = _wall_band_candidates(analysis, depth, 110.0, use_solid=False, blockers=blockers)
        tight = True
    if not cands:
        return []

    max_extent = max(c.extent for c in cands)
    zones: list[ZoneData] = []
    for i, cand in enumerate(cands):
        win_ratio = _window_overlap_ratio(cand.wall, cand.lo, cand.hi)
        entry_norm = _entry_distance_norm(analysis, cand.piece)
        corridor_ratio = _corridor_overlap_ratio(analysis, cand.piece)
        score = (
            0.50 * (cand.extent / max_extent)
            + 0.25 * (1.0 - 0.7 * win_ratio)
            + 0.25 * entry_norm
            - 0.15 * corridor_ratio
        )
        reasons = [R_HEADBOARD_TO_WALL]
        if cand.wall.is_longest_clear:
            reasons.append(R_LONGEST_CLEAR_WALL)
        if corridor_ratio < 0.05:
            reasons.append(R_KEEPS_ENTRY_OPEN)
        if win_ratio > 0.2:
            reasons.append(R_NEAR_WINDOW)
        if tight:
            reasons.append(R_TIGHT_SPACE)
        zones.append(_band_zone(analysis, cand, "bed", i, score, reasons, depth))
    return _rank(zones)


def _bedside_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """Nightstand spots flanking the bed at the headboard (left + right).

    Returns up to two side zones; the mirror_pair count rule places one per zone that
    fits. Door swing / entry / window strips are carved out, and the gate validates the
    final pose - so a side blocked by a door or wall simply yields no zone there.
    """
    bed = _find_placed(placed, "bed")
    if bed is None:
        return []
    item, product = bed
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    blockers = _placed_blockers(placed)

    zones: list[ZoneData] = []
    for idx, side in enumerate((-1.0, 1.0)):
        origin = add((item.x, item.y), w, side * (product.width_cm / 2.0 + 4.0))
        head = add(origin, f, -(product.depth_cm / 2.0 - 35.0))  # toward the headboard
        rect = item_polygon(*add(head, w, side * 30.0), 60.0, 60.0, item.rotation_deg)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        piece = largest_piece(clipped)
        if piece is None or piece.area < 1_200.0:
            continue
        zones.append(
            _frame_zone(
                "side_table", idx, piece, 0.85 if side < 0 else 0.84, item.rotation_deg,
                head, (w[0] * side, w[1] * side), f, 60.0, 60.0,
                [R_EASY_REACH], f"bed_{'left' if side < 0 else 'right'}", kind="side",
            )
        )
    return _rank(zones, limit=2)


def _majlis_sofa_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """Perimeter seating for a Majlis: wall-band zones along the longest clear walls.

    Unlike the living-room ``_sofa_zones`` (which picks the single best wall facing a
    focal/TV wall), this returns ONE inward-facing band per wall - longest wall first -
    so the orchestrator can line benches around 2-3 walls and leave the centre open.
    Door swing / entry / window keep-out is inherited from ``_wall_band_candidates``
    (which clips to ``keep_clear_union``) and enforced again by ``validate_item``.
    """
    s = stats.get("sofa", {})
    depth = s.get("max_d", 105.0) + 10.0
    blockers = _placed_blockers(placed)

    cands = _wall_band_candidates(analysis, depth, 140.0, use_solid=False, blockers=blockers)
    if not cands:
        cands = _wall_band_candidates(analysis, depth, 90.0, use_solid=False, blockers=blockers)
    if not cands:
        return []

    # one zone per wall: the longest clear band on that wall
    best_per_wall: dict[int, _BandCandidate] = {}
    for c in cands:
        cur = best_per_wall.get(c.wall.index)
        if cur is None or c.extent > cur.extent:
            best_per_wall[c.wall.index] = c

    max_extent = max(c.extent for c in best_per_wall.values())
    zones: list[ZoneData] = []
    for i, cand in enumerate(sorted(best_per_wall.values(), key=lambda c: -c.extent)):
        win_ratio = _window_overlap_ratio(cand.wall, cand.lo, cand.hi)
        corridor_ratio = _corridor_overlap_ratio(analysis, cand.piece)
        score = (
            0.60 * (cand.extent / max_extent)
            + 0.20 * (1.0 - 0.5 * win_ratio)
            - 0.20 * corridor_ratio
        )
        reasons = [R_MAJLIS_PERIMETER_SEATING, R_MAXIMIZE_SEATING, R_KEEP_CENTER_OPEN]
        if cand.wall.is_longest_clear or cand.extent >= 0.9 * max_extent:
            reasons.append(R_LONG_CLEAR_WALL)
        if corridor_ratio < 0.05:
            reasons.append(R_KEEPS_ENTRY_OPEN)
        if win_ratio > 0.2:
            reasons.append(R_NEAR_WINDOW)
        zones.append(_band_zone(analysis, cand, "sofa", i, score, reasons, depth))
    return _rank(zones, limit=4)


def _majlis_zones(
    category: str, analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData] | None:
    """Majlis overrides for the centre-of-room categories and perimeter seating.

    Returns None for categories with no Majlis-specific behaviour, so the caller
    falls through to the standard per-category generator (side_table, lighting,
    storage, decor, accent_chair keep their existing sofa-anchored / corner logic).
    """
    if category == "sofa":
        return _majlis_sofa_zones(analysis, placed, stats)
    if category == "rug":
        s = stats.get("rug", {})
        return _free_zone_center(analysis, "rug", s.get("max_w", 300.0), s.get("max_d", 240.0))
    if category == "coffee_table":
        # low table centred on the (centred) rug / room centre
        return _free_zone_center(analysis, "coffee_table", 140.0, 120.0)
    return None


_GENERATORS = {
    "sofa": _sofa_zones,
    "tv_unit": _tv_zones,
    "rug": _rug_zones,
    "coffee_table": _coffee_table_zones,
    "side_table": _side_table_zones,
    "accent_chair": _accent_chair_zones,
    "lighting": _lighting_zones,
    "storage": _storage_zones,
    "decor": _decor_zones,
}


def zones_for_category(
    category: str,
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    stats: CategoryStats,
    room_type: str | None = None,
) -> list[ZoneData]:
    # room_type defaults to None -> existing living-room behaviour, unchanged.
    if room_type == "majlis":
        majlis = _majlis_zones(category, analysis, placed, stats)
        if majlis is not None:
            return majlis
    gen = _GENERATORS.get(category)
    return gen(analysis, placed, stats) if gen else []


def initial_zones(analysis: RoomAnalysis, stats: CategoryStats) -> list[ZoneData]:
    """Zones shown right after room analysis (before the guide starts): sofa."""
    return zones_for_category("sofa", analysis, [], stats)


def anchor_pose(zone: ZoneData, product: Product, analysis: RoomAnalysis) -> Pose:
    """Concrete placement pose for a product inside a zone."""
    if zone.kind == "wall_band" and zone.wall_index is not None and zone.seg is not None:
        wall = analysis.walls[zone.wall_index]
        a, b = zone.seg
        half = product.width_cm / 2.0
        mid = (a + b) / 2.0
        if b - a > product.width_cm + 4.0:
            mid = min(max(mid, a + half + 2.0), b - half - 2.0)
        center = add(wall.point_at(mid), wall.normal, product.depth_cm / 2.0 + 4.0)
        return Pose(x=round(center[0], 1), y=round(center[1], 1), rotation_deg=zone.rotation_deg)

    if zone.kind == "frame" and zone.origin is not None and zone.fwd is not None:
        center = add(zone.origin, zone.fwd, product.depth_cm / 2.0)
        return Pose(x=round(center[0], 1), y=round(center[1], 1), rotation_deg=zone.rotation_deg)

    if zone.kind == "side" and zone.origin is not None and zone.fwd is not None:
        center = add(zone.origin, zone.fwd, product.width_cm / 2.0 + 2.0)
        return Pose(x=round(center[0], 1), y=round(center[1], 1), rotation_deg=zone.rotation_deg)

    c = zone.polygon.centroid
    return Pose(x=round(c.x, 1), y=round(c.y, 1), rotation_deg=zone.rotation_deg)


def fits_zone(zone: ZoneData, product: Product, margin: float = 1.0) -> bool:
    """Hard gate: can the product physically sit in this zone?"""
    if zone.kind == "wall_band" and zone.seg is not None:
        # a wall piece needs a sliver of practical clearance - exact-flush fits
        # always collide with jambs or swing arcs in real placement
        a, b = zone.seg
        return product.width_cm <= (b - a) * margin - 4.0 and product.depth_cm <= zone.band_depth * margin + 6.0
    if zone.kind in ("frame", "side"):
        return (
            product.width_cm <= zone.lat_len * margin + 2.0
            and product.depth_cm <= zone.fwd_len * margin + 2.0
        )
    # free zones: compare against the polygon's oriented envelope
    rect = zone.polygon.minimum_rotated_rectangle
    if rect.is_empty:
        return False
    xs = list(rect.exterior.coords)
    e1 = math.hypot(xs[1][0] - xs[0][0], xs[1][1] - xs[0][1])
    e2 = math.hypot(xs[2][0] - xs[1][0], xs[2][1] - xs[1][1])
    lo, hi = sorted((e1, e2))
    pw, pd = sorted((product.width_cm, product.depth_cm))
    return pw <= lo * margin + 2.0 and pd <= hi * margin + 2.0


def zone_utilization(zone: ZoneData, product: Product) -> float:
    if zone.kind == "wall_band" and zone.seg is not None:
        a, b = zone.seg
        return product.width_cm / max(b - a, 1.0)
    if zone.kind in ("frame", "side"):
        return product.width_cm / max(zone.lat_len, 1.0)
    return min(1.5, (product.width_cm * product.depth_cm) / max(zone.polygon.area, 1.0))
