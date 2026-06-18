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


SOFA_BACK_CM = 85.0  # a sofa back is roughly this tall; a higher window sill clears it


def _low_window_ratio(analysis: RoomAnalysis, wall: WallData, lo: float, hi: float) -> float:
    """Fraction of [lo,hi] covered by LOW windows (sill below the sofa back). A sofa
    shouldn't block these; a high window above the back is fine to sit beneath."""
    if hi <= lo:
        return 0.0
    total = 0.0
    for op in wall.openings:
        if op.kind != "window":
            continue
        strip = analysis.window_strips.get(op.id)
        sill = strip[1] if strip else 0.0
        if sill < SOFA_BACK_CM:
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
    float_cm: float = 0.0,
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
        float_cm=float_cm,
    )


def _rank(zones: list[ZoneData], limit: int = 3) -> list[ZoneData]:
    zones.sort(key=lambda z: (-z.score, z.id))
    for i, z in enumerate(zones):
        z.rank = i
    return zones[:limit]


# --- per-category generators -------------------------------------------------

VIEWING_DEPTH_CM = 400.0  # past this room depth, float the sofa in to keep a sane TV distance


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
        low_win = _low_window_ratio(analysis, cand.wall, cand.lo, cand.hi)
        entry_norm = _entry_distance_norm(analysis, cand.piece)
        corridor_ratio = _corridor_overlap_ratio(analysis, cand.piece)
        focal = 0.0
        if analysis.focal_wall_index is not None:
            focal_wall = analysis.walls[analysis.focal_wall_index]
            if dot(cand.wall.normal, focal_wall.normal) < -0.5:
                focal = 1.0
        # high windows above the sofa back are fine to sit under; low/floor windows push
        # the sofa to another wall. window_term in [0,1] (1 = no window behind the sofa).
        window_term = max(0.0, 1.0 - 0.4 * win_ratio - 0.9 * low_win)
        # big rooms: float the sofa inward so the seating forms a media group at a sane
        # viewing distance from the facing wall, instead of stranding it on a far wall.
        mid = (cand.lo + cand.hi) / 2.0
        # room depth perpendicular to this wall - start just inside so the ray doesn't
        # immediately hit the wall it starts on (which would read depth ~0).
        start_in = add(cand.wall.point_at(mid), cand.wall.normal, 10.0)
        depth_to_far = 10.0 + first_boundary_hit(analysis.polygon, start_in, cand.wall.normal)
        float_cm = max(0.0, depth_to_far - VIEWING_DEPTH_CM)
        float_cm = min(float_cm, max(0.0, depth_to_far * 0.45 - depth / 2.0))
        score = (
            0.35 * (cand.extent / max_extent)
            + 0.25 * window_term
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
        zones.append(_band_zone(analysis, cand, "sofa", i, score, reasons, depth, float_cm=float_cm))
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


BIG_ROOM_CM2 = 400_000.0  # ~40 m2: spread scatter items beyond the corners


def _long_wall_spots(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    category: str,
    size: float,
    reasons: list[str],
    min_seg: float = 220.0,
) -> list[ZoneData]:
    """Scatter spots at the midpoints of long clear walls - spreads decor/lighting
    across a large room instead of bunching everything into the corners."""
    blockers = _placed_blockers(placed, buffer_cm=8.0)
    zones: list[ZoneData] = []
    for idx, wall in enumerate(analysis.walls):
        for seg_i, (a, b) in enumerate(wall.clear_floor):
            if b - a < min_seg:
                continue
            mid = (a + b) / 2.0
            pt = add(wall.point_at(mid), wall.normal, size / 2.0 + 8.0)
            rect = item_polygon(pt[0], pt[1], size, size, 0)
            clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
            piece = largest_piece(clipped)
            if piece is None or piece.area < size * size * 0.35:
                continue
            zones.append(
                _frame_zone(
                    category, 100 + idx * 4 + seg_i, piece, 0.5, 0.0, pt, (0.0, 1.0), (1.0, 0.0),
                    size, size, reasons, f"wall_{wall.index}_mid", kind="free",
                )
            )
    return zones


def _lighting_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    near = None
    if sofa is not None:
        item, product = sofa
        f = front_vector(item.rotation_deg)
        near = add((item.x, item.y), f, product.depth_cm / 2.0)
    # all corners, ranked by proximity to the seating (no hard radius cut-off)
    zones = _corner_spots(
        analysis, placed, "lighting", 55.0, max_zones=8,
        near=near, near_radius=analysis.diag_cm if near else 0.0, reasons=[R_CORNER_LIGHT],
    )
    if analysis.area_cm2 >= BIG_ROOM_CM2:
        zones += _long_wall_spots(analysis, placed, "lighting", 55.0, [R_CORNER_LIGHT])
    if not zones:
        zones = _corner_spots(analysis, placed, "lighting", 55.0, max_zones=4, reasons=[R_CORNER_LIGHT])
    return _rank(zones, limit=4)


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
    # use every corner (ranked by proximity to the seating), not just ones within
    # a fixed radius - a large room's far corners are valid decor spots too.
    zones = _corner_spots(
        analysis, placed, "decor", 60.0, max_zones=8,
        near=near, near_radius=analysis.diag_cm if near else 0.0, reasons=[R_FLEXIBLE_SPOT],
    )
    if analysis.area_cm2 >= BIG_ROOM_CM2:
        zones += _long_wall_spots(analysis, placed, "decor", 60.0, [R_FLEXIBLE_SPOT])
    return _rank(zones, limit=6)


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
) -> list[ZoneData]:
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
        center = add(wall.point_at(mid), wall.normal, product.depth_cm / 2.0 + 4.0 + zone.float_cm)
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


# A single piece needn't fill a very long wall: cap the utilization reference so
# spatial scoring still prefers an appropriately large piece in a big room instead
# of scoring every sofa ~0 (which let a tiny budget sofa win). fits_zone still
# guards the real physical fit against the full segment.
WALL_BAND_REF_CM = 380.0


def zone_utilization(zone: ZoneData, product: Product) -> float:
    if zone.kind == "wall_band" and zone.seg is not None:
        a, b = zone.seg
        return product.width_cm / max(min(b - a, WALL_BAND_REF_CM), 1.0)
    if zone.kind in ("frame", "side"):
        return product.width_cm / max(zone.lat_len, 1.0)
    return min(1.5, (product.width_cm * product.depth_cm) / max(zone.polygon.area, 1.0))
