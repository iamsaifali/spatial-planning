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
from app.models.products import SMALL_MEDIUM_MAX_CM2, Product, placement_group
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
R_FLOATING_MEDIA = "media_at_viewing_distance"

CategoryStats = dict[str, dict[str, float]]
PlacedProduct = tuple[PlacedItem, Product]


def _find_placed(placed: list[PlacedProduct], category: str) -> PlacedProduct | None:
    for item, product in placed:
        if placement_group(product.category) == category:
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
    door_clearance: float = 0.0,
) -> list[_BandCandidate]:
    # Optional extra keep-out around door swings: the band already stops AT a swing, but a piece
    # placed flush to it reads as "touching the door". A positive door_clearance buffers each
    # swing so the band ends this many cm SHORT of it, leaving breathing room (0 = old behaviour).
    door_keepout = (
        unary_union([sw.buffer(door_clearance) for sw in analysis.swing_arcs.values()])
        if door_clearance > 0.0 and analysis.swing_arcs
        else None
    )
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
            if door_keepout is not None:
                clipped = clipped.difference(door_keepout)
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
    anchor_t: float | None = None,
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
        anchor_t=anchor_t,
    )


def _rank(zones: list[ZoneData], limit: int = 3) -> list[ZoneData]:
    zones.sort(key=lambda z: (-z.score, z.id))
    for i, z in enumerate(zones):
        z.rank = i
    return zones[:limit]


def _trim_band_extent(cands, analysis, depth, obstacles, min_len):
    """Trim each wall-band candidate's along-wall segment by the shadow of obstacles that clip a
    CORNER of its band - a door swing, OR furniture on an ADJACENT wall. When only a corner is cut,
    the band's near-wall edge stays continuous, so extent_along over-reports the run and a piece
    centred on it pokes into the obstacle (the wardrobe into the door, the vanity into a nightstand).
    Keep only the larger clear side of the notch. Returns the originals if nothing would survive."""
    if obstacles is None or getattr(obstacles, "is_empty", True):
        return cands
    out = []
    for c in cands:
        lo, hi = c.lo, c.hi
        band = quad(
            add(c.wall.point_at(lo), c.wall.normal, 2.0),
            add(c.wall.point_at(hi), c.wall.normal, 2.0),
            add(c.wall.point_at(hi), c.wall.normal, 2.0 + depth),
            add(c.wall.point_at(lo), c.wall.normal, 2.0 + depth),
        )
        shadow = obstacles.intersection(band)
        if getattr(shadow, "area", 0.0) > 1.0:
            try:
                s_lo, s_hi = extent_along(shadow, c.wall.start, c.wall.dir)
                left, right = (lo, min(hi, s_lo)), (max(lo, s_hi), hi)
                lo, hi = left if (left[1] - left[0]) >= (right[1] - right[0]) else right
            except Exception:
                lo, hi = c.lo, c.hi
        if hi - lo >= min_len:
            out.append(_BandCandidate(wall=c.wall, lo=lo, hi=hi, piece=c.piece, extent=hi - lo))
    return out or cands


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
        # A sofa that FACES a window wall forces the TV onto that window (glare + an off-centre,
        # unaligned TV). MASSIVE penalty: strongly prefer a wall whose OPPOSITE is solid so the
        # TV lands on a clear wall - even if that means the sofa itself sits under a window.
        faced = min(analysis.walls, key=lambda ww: dot(cand.wall.normal, ww.normal))
        faces_window = any(o.kind == "window" for o in faced.openings)
        score = (
            0.40 * (cand.extent / max_extent)
            + 0.20 * (1.0 - 0.5 * win_ratio)
            + 0.20 * entry_norm
            + 0.20 * focal
            - 0.15 * corridor_ratio
            - (0.7 if faces_window else 0.0)
        )
        # Great-room: the wall the sofa FACES is too far to comfortably watch a wall-mounted
        # TV from. Rather than floating the TV out to meet a wall-glued sofa, float the whole
        # SEATING GROUP forward so it sits at a human viewing distance and the TV stays on the
        # wall. The rug / coffee table / chairs anchor to the sofa's actual pose, so the whole
        # conversation area moves with it. Normal rooms don't trigger this (float stays 0).
        mid = (cand.lo + cand.hi) / 2.0
        front_pt = add(cand.wall.point_at(mid), cand.wall.normal, SOFA_FRONT_CM)
        facing_dist = first_boundary_hit(analysis.polygon, front_pt, cand.wall.normal)
        float_cm = 0.0
        if facing_dist > TV_WALL_TOO_FAR:
            tv_front_depth = stats.get("tv_unit", {}).get("max_d", 48.0) + 8.0  # TV's reach off its wall
            float_cm = max(0.0, facing_dist - tv_front_depth - TV_VIEWING_DISTANCE)
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


# Viewing geometry. A TV is comfortable ~2.5-4 m from the sofa. In a GREAT-ROOM the wall
# the sofa faces is farther than this, so the SEATING GROUP floats forward to a human
# viewing distance (see _sofa_zones) and the TV stays wall-mounted (rather than the TV
# floating out to meet a wall-glued sofa).
TV_VIEWING_DISTANCE = 330.0  # target gap: sofa front -> (wall-mounted) TV front
TV_WALL_TOO_FAR = 450.0  # facing-wall distance beyond which the seating floats forward toward the TV
SOFA_FRONT_CM = 95.0  # a typical sofa's front distance from its back wall (the exact sofa isn't chosen yet)
TV_DOOR_CLEAR_CM = 25.0  # keep the TV unit this clear of a door swing on its wall (see _tv_zones)


def _tv_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    s = stats.get("tv_unit", {})
    depth = s.get("max_d", 48.0) + 8.0
    min_w = s.get("min_w", 120.0)
    sofa = _find_placed(placed, "sofa")
    blockers = _placed_blockers(placed)

    # Keep the TV a clear margin off any door swing on its wall (a media unit flush to the door
    # reads as overlapping it); fall back to no clearance only if that leaves no viable wall.
    cands = _wall_band_candidates(analysis, depth, min_w * 0.95, use_solid=True, blockers=blockers, door_clearance=TV_DOOR_CLEAR_CM)
    if not cands:
        cands = _wall_band_candidates(analysis, depth, 90.0, use_solid=True, blockers=blockers, door_clearance=TV_DOOR_CLEAR_CM)
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
        # centre the TV on the SOFA (project its centre onto this wall), not on the wall segment
        # midpoint - so the TV sits directly in front of the sofa (a door eating one end of the
        # wall no longer shoves it off to the side), clamped to the clear segment.
        zones.append(_band_zone(analysis, cand, "tv_unit", i, score, reasons, depth, anchor_t=proj))
    # The TV always stays wall-mounted. In a great-room the SEATING floats forward instead
    # (see _sofa_zones), so the wall the sofa faces is now at a comfortable viewing distance.
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
    # Never request a footprint larger than the open area itself. Real catalogs carry huge
    # rugs (up to ~5x4 m); without this a giant rug would be selected and poke through the
    # walls in a normal room. Large rooms (e.g. majlis) are unaffected - the cap doesn't bind.
    minx, miny, maxx, maxy = usable.bounds
    size_w = max(60.0, min(size_w, (maxx - minx) - 30.0))
    size_d = max(60.0, min(size_d, (maxy - miny) - 30.0))
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

    # The primary sofa is the WIDEST placed sofa (an L-return sofa is narrower/secondary).
    sofas = [(i, p) for i, p in placed if placement_group(p.category) == "sofa"]
    item, product = max(sofas, key=lambda ip: ip[1].width_cm) if sofas else sofa
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    # Steer the single side table to the side that hosts the SECONDARY seating (the L-return
    # sofa, or an accent chair), so it serves both seats. If no companion seat is placed yet,
    # keep the neutral default (left slightly preferred).
    secondary = next((ip for ip in sofas if ip[0] is not item), None) or _find_placed(placed, "accent_chair")
    target_side = 0.0
    if secondary is not None:
        sec_item = secondary[0]
        target_side = 1.0 if dot(sub2((sec_item.x, sec_item.y), (item.x, item.y)), w) >= 0 else -1.0
    blockers = _placed_blockers(placed)
    zones: list[ZoneData] = []
    for idx, side in enumerate((-1.0, 1.0)):
        origin = add((item.x, item.y), w, side * (product.width_cm / 2.0 + 4.0))
        rect = item_polygon(*add(origin, w, side * 35.0), 78.0, max(product.depth_cm, 80.0), item.rotation_deg)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        piece = largest_piece(clipped)
        if piece is None or piece.area < 1_500.0:
            continue
        if target_side != 0.0:
            # Strongly prefer the companion-seat side; the other side stays only as a fallback
            # for when that side can't fit the table.
            score = 0.95 if side == target_side else 0.45
        else:
            score = 0.85 if side < 0 else 0.84
        zones.append(
            _frame_zone(
                "side_table", idx, piece, score, item.rotation_deg,
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
    w = width_axis(item.rotation_deg)
    blockers = _placed_blockers(placed)
    # Keep the chair a clear margin off any door swing (like corner accents do). A chair in/beside the
    # doorway is a bad template; carving the buffered swing out of every candidate makes such a spot
    # shrink below the fit threshold, so the chair lands elsewhere or is skipped - never in the door.
    door_keepout = unary_union([sw.buffer(45.0) for sw in analysis.swing_arcs.values()])
    tv = _find_placed(placed, "tv_unit")

    if tv is None:
        # No TV (majlis comfort seating): original conversation-angle placement, unchanged.
        seat_anchor = add((item.x, item.y), f, product.depth_cm / 2.0 + 60.0)
        zones: list[ZoneData] = []
        for idx, ang in enumerate((-55.0, 55.0)):
            g = rotate_vec(f, ang)
            center = add(seat_anchor, g, 170.0)
            rotation = rotation_for_normal(unit(*sub2(seat_anchor, center)))
            rect = item_polygon(center[0], center[1], 120.0, 120.0, rotation)
            clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers).difference(door_keepout)
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

    # Living room: tuck the chair against the SIDE wall, beside the sofa and clear of the TV
    # (not drifting out in front of it), angled toward the conversation centre.
    CHAIR_HALF = 42.0  # ~half an accent-chair footprint
    coffee = _find_placed(placed, "coffee_table")
    gc = (coffee[0].x, coffee[0].y) if coffee is not None else add((item.x, item.y), f, product.depth_cm / 2.0 + 80.0)
    # steer a single chair to the side AWAY from a placed storage/console (balances the group)
    storage = _find_placed(placed, "storage")
    storage_side = 0.0
    if storage is not None:
        storage_side = 1.0 if dot(sub2((storage[0].x, storage[0].y), (item.x, item.y)), w) >= 0 else -1.0
    # cap how far FORWARD (toward the TV) the chair may sit, so it stays clear of the TV
    tv_front = add((tv[0].x, tv[0].y), front_vector(tv[0].rotation_deg), tv[1].depth_cm / 2.0)
    max_fwd_extra = min(80.0, dot(sub2(tv_front, (item.x, item.y)), f) - product.depth_cm / 2.0 - CHAIR_HALF - 60.0)
    zones = []
    for idx, side in enumerate((-1.0, 1.0)):
        # Never flank the sofa with a chair on the CONSOLE's side - it just crowds the console.
        # The chair goes on the clear side instead (a room with a console gets one accent chair).
        if storage_side != 0.0 and side == storage_side:
            continue
        wall_dist = first_boundary_hit(analysis.polygon, (item.x, item.y), (side * w[0], side * w[1]))
        lat = wall_dist - CHAIR_HALF - 14.0
        fwd = product.depth_cm / 2.0 + max(0.0, min(70.0, max_fwd_extra))
        center = add(add((item.x, item.y), w, side * lat), f, fwd)
        toward = unit(*sub2(gc, center))
        rotation = rotation_for_normal(toward)
        rect = item_polygon(center[0], center[1], 100.0, 100.0, rotation)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers).difference(door_keepout)
        piece = largest_piece(clipped)
        if piece is None or piece.area < 3_500.0:
            continue
        corridor_pen = _corridor_overlap_ratio(analysis, piece)
        zones.append(
            _frame_zone(
                "accent_chair", idx, piece, 0.8 - 0.2 * corridor_pen, rotation,
                center, toward, w, 100.0, 100.0,
                [R_CONVERSATION_ANGLE], "beside_seating", kind="free",
            )
        )
    return _rank(zones, limit=2)


def _return_sofa_zone_floor() -> tuple[float, float]:
    """Minimum (width, depth) the L-return zone must reach to fit a REAL 2-seater, derived from the
    CATALOG so it needs no per-style magic constant and self-adjusts to any catalog. The WIDTH floor is
    the WIDEST of each style's NARROWEST 2-seater: whatever style narrows the pool, its slimmest 2-seater
    still fits (e.g. Islamic's only 2-seaters are 170cm, so a 140cm 'Islamic' primary must not cap the
    zone at 140). The DEPTH floor is the deepest 2-seater. Falls back to sane defaults when the catalog
    has no tagged 2-seater-sofa rows (the fixture catalog), keeping the goldens unchanged."""
    from app.models.style_metadata import STYLES
    from app.services.catalog.repository import get_repository

    twos = [p for p in get_repository().in_category("sofa") if p.category == "2-seater-sofa"]
    if not twos:
        return 170.0, 110.0  # fixture catalog has no store-category 2-seaters
    per_style_min = [
        min(p.width_cm for p in twos if st in p.styles) for st in STYLES if any(st in p.styles for p in twos)
    ]
    floor_w = max(per_style_min) if per_style_min else max(p.width_cm for p in twos)
    floor_d = max(p.depth_cm for p in twos)
    return floor_w, floor_d


def _l_return_sofa_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    """A perpendicular RETURN sofa at one end of the primary, forming an L-sectional.

    Fires only when the primary is the SOLE sofa AND there is genuinely clear room for the
    return at its front corner - so small rooms yield nothing (and the caller falls back to
    accent chairs). Returns the viable side(s) best-first (the more open side wins); empty
    once a second sofa already exists (an L is a pair, never a U)."""
    sofas = [(i, p) for i, p in placed if placement_group(p.category) == "sofa"]
    if len(sofas) != 1:
        return []
    if analysis.area_cm2 < SMALL_MEDIUM_MAX_CM2:  # match the 3-seater threshold (24 m2): a room big
        return []
    item, product = sofas[0]
    f = front_vector(item.rotation_deg)  # primary faces the TV / conversation
    w = width_axis(item.rotation_deg)
    hw, hd = product.width_cm / 2.0, product.depth_cm / 2.0
    # The return zone must fit a REAL 2-seater. Never let an abnormally narrow/shallow primary (e.g. a
    # mislabeled 140x80cm "3-seater" a style/colour pick lands on) starve the zone so no standard
    # 2-seater fits - that silently drops the L-return and falls back to a small-room accent chair.
    # Floor BOTH width and depth at CATALOG-DERIVED 2-seater dimensions (see _return_sofa_zone_floor -
    # no per-style magic constant; self-adjusts). No-op for a normal wide primary; rescues a small one.
    floor_w, floor_d = _return_sofa_zone_floor()
    ret_w = max(product.width_cm, floor_w)
    ret_d = max(product.depth_cm, floor_d)
    blockers = _placed_blockers(placed)
    swings = list(analysis.swing_arcs.values())
    zones: list[ZoneData] = []
    for idx, s in enumerate((-1.0, 1.0)):
        facing = (-s * w[0], -s * w[1])  # the return faces inward, across the L toward the primary
        # Beside the primary's END (past its width, in the open flank) and forward to its front
        # line: the return runs perpendicular along the sofa's facing axis, forming the L WITHOUT
        # reaching into the centred rug/coffee that sit in the L's opening.
        center = add(add((item.x, item.y), w, s * (hw + ret_d / 2.0 + 12.0)), f, hd + ret_w / 2.0)
        rotation = rotation_for_normal(facing)
        rect = item_polygon(center[0], center[1], ret_w, ret_d, rotation)
        piece = largest_piece(
            rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        )
        if piece is None or piece.area < 0.9 * ret_w * ret_d:
            continue  # not enough clear room for the return on this side (small room -> skip)
        gap = piece.distance(analysis.polygon.exterior)  # prefer the more open side...
        # ...and strongly prefer the end AWAY from the door, so the L opens into the room rather
        # than wrapping the entry (a return beside the doorway blocks the walk-in).
        door_far = min((piece.distance(sw) for sw in swings), default=250.0)
        score = 0.75 + 0.08 * min(gap, 50.0) / 50.0 + 0.20 * min(door_far, 250.0) / 250.0
        zones.append(
            _frame_zone(
                "sofa", idx, piece, score, rotation,
                center, facing, f, ret_d, ret_w,
                [R_ANCHORS_SEATING, R_CONVERSATION_ANGLE], "l_return_sofa", kind="free",
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
    far_from: Vec | None = None,
    face: Vec | None = None,
    blocker_buffer: float = 8.0,
) -> list[ZoneData]:
    blockers = _placed_blockers(placed, buffer_cm=blocker_buffer)
    swings = list(analysis.swing_arcs.values())
    # Keep a free-standing accent a clear margin off any door swing: subtract a BUFFERED swing
    # from each corner so a corner the door eats into shrinks below the fit threshold and is
    # skipped, rather than cramming a plant/lamp into the doorway.
    door_keepout = unary_union([sw.buffer(30.0) for sw in swings]) if swings else None
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
        if door_keepout is not None:
            clipped = clipped.difference(door_keepout)  # hold the accent clear of the door swing
        piece = largest_piece(clipped)
        if piece is None or piece.area < size * size * 0.35:
            continue
        score = 0.7
        if near is not None:
            score = 0.7 + 0.3 * (1.0 - min(1.0, dist(pt, near) / max(near_radius, 1.0)))
        elif far_from is not None:
            score = 0.7 + 0.3 * min(1.0, dist(pt, far_from) / 500.0)  # prefer the corner FARTHEST from the anchor
        # a conversation piece (reading chair) turns to FACE an anchor (the bed); others sit square
        rot = 0.0
        if face is not None:
            rot = math.degrees(math.atan2(-(face[0] - pt[0]), face[1] - pt[1]))
        zones.append(
            _frame_zone(
                category, idx, piece, score, rot, pt, (0.0, 1.0), (1.0, 0.0),
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


def _storage_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats, room_type: str = "living_room"
) -> list[ZoneData]:
    # SEPARATE handling per storage TYPE - they want different walls:
    #   console (living)     : a fully CLEAN wall (never behind the seating or across a path); optional.
    #   wardrobe (bedroom 1st): any clear wall; part of the set, sized to the room, never skipped on size.
    #   dressing-table (2nd) : a clean wall with room to SIT at it; may use the clear part of a door wall.
    already_storage = any(placement_group(pr.category) == "storage" for _it, pr in placed)
    target = ("dressing-table" if already_storage else "wardrobe") if room_type == "bedroom" else "console"

    if target == "console" and analysis.area_cm2 < SMALL_MEDIUM_MAX_CM2:
        return []  # a console just crowds a small/medium living room
    s = stats.get("storage", {})
    depth = s.get("max_d", 45.0) + 6.0
    min_w = min(s.get("min_w", 80.0), 80.0)
    # Bedroom storage keeps a clear margin off the bed/other pieces (not the old 5cm); living console
    # keeps the tight buffer (its goldens hold).
    blockers = _placed_blockers(placed, buffer_cm=30.0 if room_type == "bedroom" else 5.0)
    cands = _wall_band_candidates(analysis, depth, min_w, use_solid=True, blockers=blockers)
    if not cands:
        return []
    # Trim a candidate's run where a door swing (bedroom: OR adjacent-wall furniture) clips its
    # corner. Also done for a console in a TV room, so it can use the CLEAR part of a wall that also
    # carries a door (e.g. behind a floated sofa whose back wall has the door in one corner) instead
    # of losing the whole wall to the window wall. Keyed on the TV (not room_type) because a majlis
    # has no TV - keeping the majlis golden and the legacy<->recipe equivalence intact.
    has_tv = _find_placed(placed, "tv_unit") is not None
    if room_type == "bedroom" or (target == "console" and has_tv):
        obs = [blockers] if (room_type == "bedroom" and blockers is not None and not blockers.is_empty) else []
        obs += [sw.buffer(TV_DOOR_CLEAR_CM) for sw in analysis.swing_arcs.values()]
        if obs:
            cands = _trim_band_extent(cands, analysis, depth, unary_union(obs), min_w)

    tv = _find_placed(placed, "tv_unit")
    tv_wall = None
    if tv is not None:
        tv_f = front_vector(tv[0].rotation_deg)
        tv_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, tv_f))
    door_walls = {d.wall_index for d in analysis.room.doors}
    sofa_polys = [
        item_polygon(it.x, it.y, pr.width_cm, pr.depth_cm, it.rotation_deg)
        for it, pr in placed if placement_group(pr.category) == "sofa"
    ]
    # Living-room console: it must never SHARE A WALL with a sofa that HUGS that wall (a cramped
    # side-by-side) - not just be clear of it in its own segment. But a sofa FLOATED forward
    # (great-room seating pulled toward the TV) leaves its back wall FREE, and a console tucked
    # behind it is a good use of that dead space (see the sofa_in_front 90cm-reach test below). So a
    # sofa OWNS (excludes) its back wall only when it sits within ~55cm of it; a floated sofa does not.
    sofa_walls: set[int] = set()
    for it, pr in placed:
        if placement_group(pr.category) != "sofa":
            continue
        sf = front_vector(it.rotation_deg)
        back = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, sf))
        c = item_polygon(it.x, it.y, pr.width_cm, pr.depth_cm, it.rotation_deg).centroid
        back_gap = dot(sub2((c.x, c.y), analysis.walls[back].start), analysis.walls[back].normal) - pr.depth_cm / 2.0
        if back_gap <= 55.0:
            sofa_walls.add(back)  # a hugging sofa owns its back wall; a floated one leaves it free
    # Among the clean walls that remain, PREFER the wall BEHIND the primary sofa. When the primary
    # HUGS its wall that wall is excluded above, so this bonus fires only for a FLOATED primary -
    # tucking the console into the dead space behind the seating - else it falls through to the
    # clearest-wall ranking as before.
    # Behind a floated primary is only good when there is REAL room to stand at and use the console -
    # a console tucked into a ~75cm gap leaves ~24cm of access, too cramped to open/reach. So require
    # the primary's back edge to clear the wall by a console depth + a standing zone (~106cm) before
    # treating its back wall as a usable "behind" spot; otherwise the console takes a secondary clean
    # wall (or is skipped).
    USABLE_BEHIND = depth + 55.0
    primary_sofa = _find_placed(placed, "sofa")
    behind_wall = None
    behind_usable = False
    if primary_sofa is not None:
        psf = front_vector(primary_sofa[0].rotation_deg)
        behind_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, psf))
        pit, ppr = primary_sofa
        pc = item_polygon(pit.x, pit.y, ppr.width_cm, ppr.depth_cm, pit.rotation_deg).centroid
        primary_back_gap = dot(sub2((pc.x, pc.y), analysis.walls[behind_wall].start), analysis.walls[behind_wall].normal) - ppr.depth_cm / 2.0
        behind_usable = primary_back_gap >= USABLE_BEHIND
    furniture_polys = [
        item_polygon(it.x, it.y, pr.width_cm, pr.depth_cm, it.rotation_deg)
        for it, pr in placed if not pr.is_walkable
    ]
    storage_walls: set[int] = set()  # a 2nd storage piece should take a DIFFERENT wall
    for it, pr in placed:
        if placement_group(pr.category) == "storage":
            sf = front_vector(it.rotation_deg)
            storage_walls.add(max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, sf)))
    max_extent = max(c.extent for c in cands)

    def region(cand, extra):  # the band, extended `extra` cm forward - a clearance/approach test
        w = cand.wall
        return quad(
            add(w.point_at(cand.lo), w.normal, 2.0), add(w.point_at(cand.hi), w.normal, 2.0),
            add(w.point_at(cand.hi), w.normal, 2.0 + depth + extra),
            add(w.point_at(cand.lo), w.normal, 2.0 + depth + extra),
        )

    zones: list[ZoneData] = []
    for i, cand in enumerate(cands):
        w = cand.wall
        blocks_walkway = _corridor_overlap_ratio(analysis, cand.piece) > 0.05
        pen = 0.0
        if target == "console":
            # Not the TV/door wall, no walkway. Reject a sofa in the band OR jammed so close in front
            # that the console becomes a 40cm SLIVER with no room to pass - but a sofa FLOATED well
            # forward (great-room seating pulled toward the TV) leaves the wall behind it free, and a
            # console behind a floated sofa is a good use of that dead space. So the "in front" test
            # only reaches ~a console depth + a walkway (~90cm) ahead: a sofa nearer than that blocks
            # the wall; one floated beyond it does not.
            sofa_in_band = any(region(cand, 0.0).intersection(sp).area > 5_000.0 for sp in sofa_polys)
            # A sofa blocks this wall for a console UNLESS it is floated forward far enough to leave a
            # USABLE console behind it. Per sofa (covers the primary AND the L-return): if it backs onto
            # THIS wall and clears the standing zone (back_gap >= USABLE_BEHIND ~ console depth + 55cm)
            # it's exempt - the console tucks into that usable dead space; if it backs onto this wall but
            # is closer than that AND sits in front of the console's span, it blocks (too cramped to
            # use). A sofa NOT backing onto this wall blocks only when jammed close in front (the legacy
            # region+area reach). has_tv gates majlis to the original behaviour (byte-identical) - a
            # majlis sofa never floats, so it always takes the legacy reach test below.
            sofa_in_front = False
            for it2, pr2 in placed:
                if placement_group(pr2.category) != "sofa":
                    continue
                sp2 = item_polygon(it2.x, it2.y, pr2.width_cm, pr2.depth_cm, it2.rotation_deg)
                if has_tv:
                    sf2 = front_vector(it2.rotation_deg)
                    sbw2 = max(range(len(analysis.walls)), key=lambda k: dot(analysis.walls[k].normal, sf2))
                    if sbw2 == w.index:  # this sofa backs onto the console's wall
                        bg2 = dot(sub2((it2.x, it2.y), analysis.walls[w.index].start), analysis.walls[w.index].normal) - pr2.depth_cm / 2.0
                        if bg2 >= USABLE_BEHIND:
                            continue  # usable dead space behind a well-floated sofa
                        if region(cand, USABLE_BEHIND).intersection(sp2).area > 2_000.0:
                            sofa_in_front = True
                            break
                        continue  # cramped but off to the side (not in the console's span) - no block
                if region(cand, 90.0 if has_tv else 160.0).intersection(sp2).area > 8_000.0:
                    sofa_in_front = True
                    break
            # A TV-room console may use the CLEAR part of a door wall (its run is trimmed clear of the
            # swing above) - e.g. behind a floated sofa whose back wall carries the door in one corner.
            # A majlis (no TV) keeps a door wall off-limits. Keyed on has_tv (not room_type) so the
            # legacy and recipe paths behave identically for majlis. TV wall / sofa in band / blocked
            # walkway always disqualify.
            on_door_wall = w.index in door_walls and not has_tv
            # Living-room only (keyed on has_tv, like the other console rules): a majlis salon keeps
            # its legacy placement byte-identical, so this wall-level sofa exclusion must not touch it.
            shares_sofa_wall = has_tv and w.index in sofa_walls
            if (tv_wall is not None and w.index == tv_wall) or on_door_wall or shares_sofa_wall or sofa_in_band or sofa_in_front or blocks_walkway:
                continue
        elif target == "dressing-table":
            # USABLE vanity. First keep its run clear of NIGHTSTANDS - small items on the bed's
            # adjacent wall whose corner the band-trim can miss: project each nearby nightstand onto
            # this wall and carve out a keep-clear interval, keeping the larger clear side.
            lo, hi = cand.lo, cand.hi
            for it, pr in placed:
                if placement_group(pr.category) != "side_table":
                    continue
                rel = sub2((it.x, it.y), w.start)
                if not (0.0 < dot(rel, w.normal) < depth + 60.0):
                    continue  # nightstand not near this wall's approach
                proj = dot(rel, w.dir)
                clr = max(pr.width_cm, pr.depth_cm) / 2.0 + 40.0 + 47.5  # nightstand + gap + vanity half
                a, b = proj - clr, proj + clr
                if b <= lo or a >= hi:
                    continue
                left, right = (lo, min(hi, a)), (max(lo, b), hi)
                lo, hi = left if (left[1] - left[0]) >= (right[1] - right[0]) else right
            if hi - lo < min_w:
                lo, hi = cand.lo, cand.hi
                pen += 0.7  # can't clear a nightstand on this wall - a last resort, not a skip
            cand = _BandCandidate(wall=w, lo=lo, hi=hi, piece=cand.piece, extent=hi - lo)
            # Prefer a wall with sitting room in front and off the walkway, but DON'T drop it - a
            # vanity hugs the wall, so penalise instead, so it always lands on the BEST available wall
            # (a clear one) rather than being skipped entirely.
            if any(region(cand, 55.0).intersection(fp).area > 6_000.0 for fp in furniture_polys):
                pen += 0.4
            if blocks_walkway:
                pen += 0.3
        else:  # wardrobe: any clear wall (blockers + the corner trim already keep it off things)
            if blocks_walkway:
                continue
        score = 0.7 * (cand.extent / max_extent) + 0.3 * _entry_distance_norm(analysis, cand.piece) - pen
        if target == "console" and has_tv and behind_usable and w.index == behind_wall:
            score += 0.5  # tuck the console behind a FLOATED primary sofa (only if usable room behind)
        if w.index in storage_walls:
            score -= 0.5  # a wall already carrying storage - prefer a different one (fall back if forced)
        zones.append(_band_zone(analysis, cand, "storage", i, score, [R_REMAINING_WALL], depth))
    return _rank(zones)


def _decor_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    near = (sofa[0].x, sofa[0].y) if sofa is not None else None
    # Prefer corners near the seating, but consider EVERY corner (radius = room diagonal): in a
    # big room the near corners are often taken by lamps, so a plant should still fill an empty
    # far corner rather than being skipped.
    return _corner_spots(
        analysis, placed, "decor", 60.0, max_zones=4,
        near=near, near_radius=analysis.diag_cm if near else 0.0, reasons=[R_FLEXIBLE_SPOT],
    )


def _lamp_on_table_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """A table lamp resting ON a nightstand: one small free zone centred on the first placed
    side table, sized to (most of) its top so only a small lamp fits - not a floor lamp. The
    lamp shares the table's footprint; that overlap is expected and exempted in validation."""
    table = _find_placed(placed, "side_table")
    if table is None:
        return []  # no nightstand to stand on -> no lamp
    item, product = table
    s = min(product.width_cm, product.depth_cm) * 0.8  # fits a small lamp base on the table top
    poly = item_polygon(item.x, item.y, s, s, item.rotation_deg)
    return [
        _frame_zone(
            "lighting", 0, poly, 0.9, item.rotation_deg,
            (item.x, item.y), (0.0, 1.0), (1.0, 0.0), s, s,
            [R_FLEXIBLE_SPOT], "on_nightstand", kind="free",
        )
    ]


def _vases_on_console_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """Two accents (vases) spaced along the TOP of the console (storage). They share the
    console's footprint - that overlap is expected and exempted in validation."""
    console = _find_placed(placed, "storage")
    if console is None:
        return []  # no console to stand on -> no vases
    item, product = console
    w = width_axis(item.rotation_deg)
    s = min(product.depth_cm - 8.0, 42.0)  # a small vase footprint that sits on the console top
    zones: list[ZoneData] = []
    for idx, frac in enumerate((-0.28, 0.28)):  # spaced toward each end of the console
        center = add((item.x, item.y), w, frac * product.width_cm)
        poly = item_polygon(center[0], center[1], s, s, item.rotation_deg)
        zones.append(
            _frame_zone(
                "decor", idx, poly, 0.9, item.rotation_deg,
                center, (0.0, 1.0), (1.0, 0.0), s, s,
                [R_FLEXIBLE_SPOT], f"on_console_{idx}", kind="free",
            )
        )
    return zones


def _reading_chair_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """A single reading chair in the corner FARTHEST from the bed that is clear and door-free.
    Door corners shrink below the fit threshold via the swing buffer, and occupied corners are
    excluded as blockers - so what remains is the empty, doorless corner opposite the bed."""
    bed = _find_placed(placed, "bed")
    far = (bed[0].x, bed[0].y) if bed is not None else None
    # The chair is a NICE-TO-HAVE placed after the wardrobe + dressing table: it needs a genuinely
    # clear corner (a wide 35cm clearance off any furniture), otherwise no zone is produced and the
    # chair is simply skipped rather than crammed beside the vanity.
    return _corner_spots(
        analysis, placed, "accent_chair", 70.0, max_zones=1, far_from=far, face=far,
        reasons=[R_FLEXIBLE_SPOT], blocker_buffer=35.0,
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
        # A bed wants a SOLID wall for the headboard, not the longest wall. Once a wall is
        # long enough to hold the bed, extra length barely matters - so the fit term
        # saturates, and a window on the headboard wall is a strong penalty (designers
        # avoid beds under windows). The user can still pick an under-window template.
        fit = min(1.0, cand.extent / (min_w + 50.0))
        score = (
            0.28 * fit
            + 0.45 * (1.0 - win_ratio)
            + 0.18 * entry_norm
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
    # A nightstand beside a headboard next to a door must keep clear of the swing, not just
    # avoid a >5% overlap. Buffer the swing so a side with no clear room yields no zone (the
    # bed then gets a single nightstand on the clear side, rather than one jammed in the door).
    swings = list(analysis.swing_arcs.values())
    door_keepout = unary_union([sw.buffer(20.0) for sw in swings]) if swings else None

    zones: list[ZoneData] = []
    for idx, side in enumerate((-1.0, 1.0)):
        origin = add((item.x, item.y), w, side * (product.width_cm / 2.0 + 4.0))
        head = add(origin, f, -(product.depth_cm / 2.0 - 35.0))  # toward the headboard
        rect = item_polygon(*add(head, w, side * 30.0), 60.0, 60.0, item.rotation_deg)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        if door_keepout is not None:
            clipped = clipped.difference(door_keepout)
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
        # aim for anchor_t (e.g. the TV aligns to the sofa's centre) when set, else the segment
        # centre; clamp so the product stays inside the clear segment.
        mid = zone.anchor_t if zone.anchor_t is not None else (a + b) / 2.0
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


def zone_utilization(zone: ZoneData, product: Product) -> float:
    if zone.kind == "wall_band" and zone.seg is not None:
        a, b = zone.seg
        return product.width_cm / max(b - a, 1.0)
    if zone.kind in ("frame", "side"):
        return product.width_cm / max(zone.lat_len, 1.0)
    return min(1.5, (product.width_cm * product.depth_cm) / max(zone.polygon.area, 1.0))
