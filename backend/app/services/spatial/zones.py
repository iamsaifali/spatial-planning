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
R_BESIDE_SEATING = "beside_seating"
R_REMAINING_WALL = "uses_remaining_wall"
R_FLEXIBLE_SPOT = "flexible_spot"

CategoryStats = dict[str, dict[str, float]]
PlacedProduct = tuple[PlacedItem, Product]


def _find_placed(placed: list[PlacedProduct], category: str) -> PlacedProduct | None:
    for item, product in placed:
        if product.category == category:
            return item, product
    return None


def _sofa_group_front(placed: list[PlacedProduct]) -> Vec | None:
    """Centre of the seating group: the mean of each sofa's front-edge midpoint. For a
    single sofa this is just that sofa's front; for an L/U it is the open conversation
    centre, so the rug and coffee table anchor to the group rather than one sofa."""
    sofas = [(i, p) for i, p in placed if p.category == "sofa"]
    if not sofas:
        return None
    pts = [add((i.x, i.y), front_vector(i.rotation_deg), p.depth_cm / 2.0) for i, p in sofas]
    return (sum(x for x, _y in pts) / len(pts), sum(y for _x, y in pts) / len(pts))


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


def _window_keepout(analysis: RoomAnalysis):
    """Floor strips in front of windows: a tall floor item (plant, floor lamp) parked
    here blocks the glass, so decor/lighting zones overlapping it are dropped."""
    polys = [strip for strip, _sill in analysis.window_strips.values()]
    return unary_union(polys) if polys else Polygon()


def _drop_window_blocking(analysis: RoomAnalysis, zones: list[ZoneData]) -> list[ZoneData]:
    keepout = _window_keepout(analysis)
    if keepout.is_empty:
        return zones
    return [z for z in zones if z.polygon.intersection(keepout).area < 300.0]


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


def _subtract_intervals(a: float, b: float, occupied: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[a,b] minus the occupied sub-intervals -> the clear sub-intervals."""
    clear = [(a, b)]
    for lo, hi in occupied:
        nxt: list[tuple[float, float]] = []
        for ca, cb in clear:
            if hi <= ca or lo >= cb:
                nxt.append((ca, cb))
                continue
            if lo > ca:
                nxt.append((ca, lo))
            if hi < cb:
                nxt.append((hi, cb))
        clear = nxt
    return clear


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
            region = band.intersection(analysis.polygon).difference(analysis.keep_clear_union)
            if region.is_empty:
                continue
            # A placed item shallower than the band leaves thin strips beside it, so the
            # band stays one connected piece and its full extent reads as clear - which let
            # a 2nd item land ON TOP. Instead remove each blocker's wall-axis span outright,
            # splitting the segment into genuinely clear sub-intervals.
            occupied: list[tuple[float, float]] = []
            if blockers is not None and not blockers.is_empty:
                for piece in pieces_of(region.intersection(blockers)):
                    lo, hi = extent_along(piece, wall.start, wall.dir)
                    occupied.append((lo - 4.0, hi + 4.0))
            for lo, hi in _subtract_intervals(a, b, occupied):
                if hi - lo < min_len:
                    continue
                sub = quad(
                    add(wall.point_at(lo), wall.normal, 2.0),
                    add(wall.point_at(hi), wall.normal, 2.0),
                    add(wall.point_at(hi), wall.normal, 2.0 + depth),
                    add(wall.point_at(lo), wall.normal, 2.0 + depth),
                )
                piece = largest_piece(
                    sub.intersection(analysis.polygon).difference(analysis.keep_clear_union)
                )
                if piece is None:
                    continue
                elo, ehi = extent_along(piece, wall.start, wall.dir)
                extent = ehi - elo
                if extent < min_len or piece.area < extent * depth * 0.45:
                    continue
                out.append(_BandCandidate(wall=wall, lo=elo, hi=ehi, piece=piece, extent=extent))
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
MAX_VIEW_CM = 420.0  # don't pull a cluster so far back that the primary's TV distance exceeds this


def _sofa_back_wall(analysis: RoomAnalysis, sofa_item: PlacedItem) -> int:
    """Infer which wall a placed sofa backs onto: its front faces that wall's inward normal."""
    f = front_vector(sofa_item.rotation_deg)
    return max(range(len(analysis.walls)), key=lambda i: dot(f, analysis.walls[i].normal))


def _additional_sofa_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], placed_sofas: list[PlacedProduct],
    stats: CategoryStats,
) -> list[ZoneData]:
    """L/U return: FLANK the primary sofa's ends with perpendicular arms facing inward,
    forming a tight group around the open conversation centre. The arm is anchored to the
    primary sofa's ACTUAL position (not a far wall) so the group stays together even when
    the primary has floated into a big room - a wall-anchored arm would strand it metres
    away. One arm per side; the side already holding a sofa is skipped. Empty -> the room
    can't take another sofa (capacity then falls to accent chairs)."""
    s = stats.get("sofa", {})
    arm_len = s.get("max_w", 240.0)
    arm_depth = s.get("max_d", 105.0) + 6.0
    primary_item, primary_prod = placed_sofas[0]
    pc = (primary_item.x, primary_item.y)
    pf = front_vector(primary_item.rotation_deg)  # primary faces the TV/centre
    pw = width_axis(primary_item.rotation_deg)
    half_w = primary_prod.width_cm / 2.0
    half_d = primary_prod.depth_cm / 2.0
    blockers = _placed_blockers(placed)
    # sides (relative to the primary's width axis) that already hold an arm
    occupied = {
        1.0 if dot(sub2((it.x, it.y), pc), pw) >= 0 else -1.0
        for it, _p in placed_sofas[1:]
    }

    zones: list[ZoneData] = []
    for idx, side in enumerate((-1.0, 1.0)):
        if side in occupied:
            continue  # one arm per side
        facing = (pw[0] * -side, pw[1] * -side)  # face inward toward the conversation centre
        # anchor at the primary's BACK corner and run the arm forward, so it aligns with
        # the primary's depth (forms the L corner) instead of reaching on toward the TV
        # wall - an arm anchored at the front corner over-extends and crowds the TV.
        corner = add(add(pc, pw, side * half_w), pf, -half_d)  # primary's BACK corner this side
        # Keep the ~20 cm lateral gap (they read as two distinct sofas, not one mass), but
        # drop the perpendicular arm DOWNWARD (forward, toward the TV) so its back edge sits
        # near the primary's FRONT rather than level with the primary's back. The arm then
        # steps down from the corner - it "starts where the primary ends" - instead of
        # running alongside the primary's depth, which read as an overlap.
        # drop so the arm's back edge sits at the primary's FRONT (corner_pf + 2*half_d):
        # forward = (arm_len/2) shifts the arm's centre forward from the back corner; the
        # extra 2*half_d steps it down past the primary's depth.
        forward = arm_len / 2.0 + 2.0 * half_d
        center = add(add(corner, pw, side * (arm_depth / 2.0 + 22.0)), pf, forward)
        rotation = rotation_for_normal(facing)
        rect = item_polygon(center[0], center[1], arm_len, arm_depth, rotation)
        piece = largest_piece(rect.intersection(analysis.polygon).difference(blockers))
        if piece is None or piece.area < arm_len * arm_depth * 0.65:
            continue  # no room beside the primary for an arm on this side
        z = _frame_zone(
            "sofa", idx, piece, 0.92 - 0.02 * idx, rotation,
            center, facing, pf, arm_depth, arm_len,
            [R_ANCHORS_SEATING, R_CONVERSATION_ANGLE], "beside_primary_sofa", kind="free",
        )
        z.place_at_origin = True  # keep the 20 cm gap; don't drift to the clipped centroid
        zones.append(z)
    return _rank(zones)


def _sofa_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats, n_planned: int = 1
) -> list[ZoneData]:
    placed_sofas = [(i, p) for i, p in placed if p.category == "sofa"]
    if placed_sofas:  # 2nd/3rd sofa -> L/U return on a perpendicular wall
        return _additional_sofa_zones(analysis, placed, placed_sofas, stats)

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
        # The sofa FACES the wall opposite its back - that's where the TV ends up. A TV
        # belongs on a clear, solid wall, not a window (glare, can't mount) and ideally not
        # a door wall. Penalise candidates that would face an opening so the primary orients
        # toward the non-window wall and the room builds around that. (Without this, pushing
        # the sofa OFF a low-window wall can leave it FACING that window wall - worse.)
        faced_window = faced_door = 0.0
        for ow in analysis.walls:
            if ow.index != cand.wall.index and dot(ow.normal, cand.wall.normal) < -0.5:
                kinds = {o.kind for o in ow.openings}
                faced_window = 1.0 if "window" in kinds else 0.0
                faced_door = 1.0 if "door" in kinds else 0.0
                break
        # big rooms: float the sofa inward so the seating forms a media group at a sane
        # viewing distance from the facing wall, instead of stranding it on a far wall.
        mid = (cand.lo + cand.hi) / 2.0
        # room depth perpendicular to this wall - start just inside so the ray doesn't
        # immediately hit the wall it starts on (which would read depth ~0).
        start_in = add(cand.wall.point_at(mid), cand.wall.normal, 10.0)
        depth_to_far = 10.0 + first_boundary_hit(analysis.polygon, start_in, cand.wall.normal)
        float_cm = max(0.0, depth_to_far - VIEWING_DEPTH_CM)
        float_cm = min(float_cm, max(0.0, depth_to_far * 0.45 - depth / 2.0))
        if n_planned >= 2:
            # An L/U adds arms that extend FORWARD of the primary, so floating the primary to
            # its own ideal viewing distance leaves the whole seating cluster crammed against
            # the TV wall (bottom-heavy). Pull the primary back so the CLUSTER is centred in
            # the room - but never so far that the primary's own TV distance exceeds
            # MAX_VIEW_CM (which would happen in a very deep room, where staying forward is
            # the right call). arm_reach = how far an arm's front sits ahead of the primary
            # centre (mirrors _additional_sofa_zones' forward offset).
            arm_reach = s.get("max_w", 240.0) / 2.0 + 1.5 * s.get("max_d", 105.0)
            cluster_offset = max(0.0, (arm_reach - depth / 2.0) / 2.0)
            centered_float = (depth_to_far / 2.0 - cluster_offset) - depth / 2.0
            min_float_for_view = (depth_to_far - 50.0) - (s.get("max_d", 105.0) + 4.0) - MAX_VIEW_CM
            float_cm = min(float_cm, max(centered_float, min_float_for_view, 0.0))
        score = (
            0.35 * (cand.extent / max_extent)
            + 0.25 * window_term
            + 0.20 * entry_norm
            + 0.20 * focal
            - 0.15 * corridor_ratio
            - 0.60 * faced_window  # never face the TV onto a window wall
            - 0.15 * faced_door  # prefer not to face a door wall either
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
        z = _band_zone(analysis, cand, "tv_unit", i, score, reasons, depth)
        # centre the TV on the sofa's projection along the wall, not the wall midpoint -
        # otherwise an off-centre sofa gets a TV placed beside it instead of in front.
        if facing and cand.hi > cand.lo:
            z.anchor_t = max(0.0, min(1.0, (proj - cand.lo) / (cand.hi - cand.lo)))
        zones.append(z)
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
    sofas = [(i, p) for i, p in placed if p.category == "sofa"]
    if not sofas:
        return _free_zone_center(analysis, "rug", s.get("max_w", 300.0), s.get("max_d", 240.0))

    item, product = sofas[0]  # the primary sofa sets the rug's orientation
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)

    if len(sofas) >= 2:
        # L/U: place the rug IN FRONT of the seating group (the open conversation quadrant
        # the sofas face), with each sofa's front edge tucked ~TUCK cm onto it (front legs
        # on rug) - NOT buried under the seating. The rug stays axis-aligned to the primary:
        # f = primary's forward, w = its width axis. This is a FRAME zone anchored at `origin`
        # whose -f edge is the rug's back edge; anchor_pose then pushes it forward by the
        # REAL rug's depth/2, so the primary front tucks exactly TUCK regardless of which rug
        # is chosen. Laterally (along w): for an L (arm on one side) we shift the rug toward
        # that arm so the arm's front tucks too; for a U (arms both sides) we centre on the
        # primary's width. est_w estimates the rug width (the real one is unknown until a
        # product is picked) to set the lateral shift.
        TUCK = 25.0
        est_w = product.width_cm + 70.0  # rug ~ primary width + overhang
        primary_front = add((item.x, item.y), f, product.depth_cm / 2.0)
        fc = dot(primary_front, f) - TUCK  # rug BACK edge tucks the primary front by TUCK

        arm_sides = set()
        arm_wc = None
        for arm_i, arm_p in sofas[1:]:
            fa = front_vector(arm_i.rotation_deg)
            side = 1.0 if dot(fa, w) >= 0 else -1.0  # +w-ward direction the arm faces
            arm_sides.add(side)
            arm_front = add((arm_i.x, arm_i.y), fa, arm_p.depth_cm / 2.0)
            arm_wc = dot(arm_front, w) + side * (est_w / 2.0 - TUCK)
        wc = arm_wc if (len(arm_sides) == 1 and arm_wc is not None) else dot((item.x, item.y), w)

        origin = (fc * f[0] + wc * w[0], fc * f[1] + wc * w[1])
        lat_len = max(product.width_cm + 70.0, s.get("max_w", 350.0) + 10.0)
        fwd_len = s.get("max_d", 250.0) + 20.0
        inner = analysis.polygon.buffer(-12.0)
        # display/fit polygon: the rug band from the back edge forward
        rect = quad(
            add(origin, w, -lat_len / 2.0),
            add(origin, w, lat_len / 2.0),
            add(add(origin, w, lat_len / 2.0), f, fwd_len),
            add(add(origin, w, -lat_len / 2.0), f, fwd_len),
        )
        piece = largest_piece(rect.intersection(inner if not inner.is_empty else analysis.polygon))
        if piece is None or piece.area < 5_000.0:
            return []
        return [
            _frame_zone(
                "rug", 0, piece, 0.92, item.rotation_deg, origin, f, w, fwd_len, lat_len,
                [R_FRONT_LEGS_ON_RUG, R_ANCHORS_SEATING], "in_front_of_group",
            )
        ]

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
    # Anchor on the PRIMARY sofa's own front, centred on its width - the group front
    # skews toward a single L-arm and pulls the table off-centre. 45 cm of clearance
    # keeps it reachable without tripping the too-tight / too-far warnings.
    sofa_front = add((item.x, item.y), f, product.depth_cm / 2.0)
    origin = add(sofa_front, f, 45.0)
    fwd_len = 75.0  # table near edge sits ~45 cm from the sofa
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




def _existing_near_sofas(
    placed: list[PlacedProduct], sofas: list[PlacedProduct], category: str,
) -> list[int]:
    """Count already-placed items of `category`, attributed to their nearest sofa.
    Lets a per-sofa generator deprioritise sofas that are already served so the next
    instance spreads to an unserved sofa (the UI re-queries after each placement)."""
    centers = [(i.x, i.y) for i, _p in sofas]
    counts = [0] * len(centers)
    if not centers:
        return counts
    for it, p in placed:
        if p.category != category:
            continue
        k = min(range(len(centers)), key=lambda j: dist((it.x, it.y), centers[j]))
        counts[k] += 1
    return counts


def _side_table_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofas = [(i, p) for i, p in placed if p.category == "sofa"]
    if not sofas:
        return _corner_spots(analysis, placed, "side_table", 70.0, max_zones=2)

    blockers = _placed_blockers(placed)
    served = _existing_near_sofas(placed, sofas, "side_table")
    zones: list[ZoneData] = []
    idx = 0
    for s_idx, (item, product) in enumerate(sofas):
        f = front_vector(item.rotation_deg)
        w = width_axis(item.rotation_deg)
        for side in (-1.0, 1.0):
            origin = add((item.x, item.y), w, side * (product.width_cm / 2.0 + 4.0))
            tbl_d = max(product.depth_cm, 80.0)
            rect = item_polygon(*add(origin, w, side * 35.0), 78.0, tbl_d, item.rotation_deg)
            clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
            piece = largest_piece(clipped)
            # require the spot to be MOSTLY clear - a heavily-clipped end abuts another
            # sofa (the inner L corner) or a wall, where a table would overlap. Skip it.
            if piece is None or piece.area < 0.55 * 78.0 * tbl_d:
                continue
            # a sofa that already has a side table drops behind any sofa with none, so
            # the 2nd table goes to the OTHER sofa instead of crowding the first.
            score = (0.85 if side < 0 else 0.84) - 0.40 * served[s_idx]
            zones.append(
                _frame_zone(
                    "side_table", idx, piece, score, item.rotation_deg,
                    origin, (w[0] * side, w[1] * side), f, 80.0, 80.0,
                    [R_EASY_REACH], f"sofa{s_idx}_{'left' if side < 0 else 'right'}", kind="side",
                )
            )
            idx += 1
    return _rank(zones, limit=2)


def _tv_view_corridor(analysis: RoomAnalysis, placed: list[PlacedProduct]) -> Polygon | None:
    """The TV->sofa sightline as a polygon (same construction as validate.py's G5),
    widened a little so flanking items stay clearly off the view. None if there is
    no TV+sofa pair yet."""
    tv = _find_placed(placed, "tv_unit")
    sofas = [(i, p) for i, p in placed if p.category == "sofa"]
    if tv is None or not sofas:
        return None
    ti, tp = tv
    f = front_vector(ti.rotation_deg)
    w = width_axis(ti.rotation_deg)
    tv_front = add((ti.x, ti.y), f, tp.depth_cm / 2.0)
    best_len = max(dot(sub2((i.x, i.y), tv_front), f) for i, _p in sofas)
    if best_len < 100.0:  # no sofa actually in front of the TV
        return None
    half = tp.width_cm / 2.0 + 10.0  # small margin around the literal TV->sofa view band
    return quad(
        add(tv_front, w, -half),
        add(tv_front, w, half),
        add(add(tv_front, w, half), f, best_len),
        add(add(tv_front, w, -half), f, best_len),
    )


def _accent_chair_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofas = [(i, p) for i, p in placed if p.category == "sofa"]
    group_front = _sofa_group_front(placed)
    if not sofas or group_front is None:
        return _corner_spots(analysis, placed, "accent_chair", 110.0, max_zones=2)

    item, product = sofas[0]  # flank the primary (TV-facing) sofa
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    blockers = _placed_blockers(placed)
    corridor = _tv_view_corridor(analysis, placed)
    CHAIR = 120.0
    tv = _find_placed(placed, "tv_unit")
    corridor_half = (tv[1].width_cm / 2.0 + 10.0) if tv is not None else 0.0
    # lateral offset: clear the TV sightline AND leave ~50 cm to the sofa (no cramped warning)
    lateral = max(product.width_cm / 2.0 + 95.0, corridor_half + CHAIR / 2.0 + 15.0)
    sofa_front = add((item.x, item.y), f, product.depth_cm / 2.0)
    coffee = _find_placed(placed, "coffee_table")
    gc = (coffee[0].x, coffee[0].y) if coffee is not None else add(sofa_front, f, 45.0)  # conversation centre
    placed_chairs = [(i.x, i.y) for i, p in placed if p.category == "accent_chair"]

    def make_zone(center: Vec, idx: int) -> ZoneData | None:
        if any(dist(center, c) < 90.0 for c in placed_chairs):
            return None  # don't stack on an existing chair (but 90 cm+ apart is fine)
        toward = unit(*sub2(gc, center))
        rotation = rotation_for_normal(toward)
        rect = item_polygon(center[0], center[1], CHAIR, CHAIR, rotation)
        piece = largest_piece(
            rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        )
        if piece is None or piece.area < 0.7 * CHAIR * CHAIR:
            return None
        if corridor is not None and piece.intersection(corridor).area > 600.0:
            return None  # never in the TV->sofa view
        corridor_pen = _corridor_overlap_ratio(analysis, piece)
        return _frame_zone(
            "accent_chair", idx, piece, 0.82 - 0.3 * corridor_pen, rotation,
            center, toward, (0.0, 1.0), CHAIR, CHAIR, [R_CONVERSATION_ANGLE], "beside_seating", kind="free",
        )

    # Only an arm SOFA makes a side off-limits for flanking. An already-placed chair does
    # NOT block its side (the make_zone 90 cm guard stops actual stacking) - so a 2nd chair
    # can join the SAME open side as a pair instead of being stranded across the room.
    taken = {
        1.0 if dot(sub2((oi.x, oi.y), (item.x, item.y)), w) >= 0 else -1.0
        for oi, op in placed
        if op.category == "sofa" and (oi.x, oi.y) != (item.x, item.y)
    }
    free_sides = [s for s in (-1.0, 1.0) if s not in taken]
    zones: list[ZoneData] = []
    idx = 0
    if free_sides:
        # SINGLE sofa (both sides free) -> one chair per side, a symmetric pair.
        # L (one arm holds the other side) -> BOTH chairs on the open side: one beside the
        # sofa, one a step forward toward the conversation centre, so they stay a tight pair
        # facing the group rather than one being flung far away.
        for side in free_sides:
            offsets = (30.0,) if len(free_sides) == 2 else (30.0, 30.0 + CHAIR + 35.0)
            for fwd in offsets:
                z = make_zone(add(add(sofa_front, w, side * lateral), f, fwd), idx)
                if z is not None:
                    zones.append(z)
                    idx += 1
    else:
        # U-FORMATION: both lateral sides hold arm sofas, so the chairs can't flank the
        # primary. Set the two chairs along the SIDE WALLS (the open left/right zones beside
        # the U), a little forward of the group and angled inward toward the conversation
        # centre. They read as intentional, keep the central floor and the TV sightline
        # clear, and still face the group rather than stranding in far corners facing a wall.
        # make_zone orients each chair at gc and rejects anything in the TV corridor.
        FORWARD = 80.0  # a little forward, toward the open/TV side
        for sd in (-1.0, 1.0):
            side_dir = (sd * w[0], sd * w[1])  # toward the left / right side wall
            wall_dist = first_boundary_hit(analysis.polygon, gc, side_dir)
            lateral = max(0.0, wall_dist - CHAIR / 2.0 - 12.0)  # sit against the wall, clear of it
            center = add(add(gc, side_dir, lateral), f, FORWARD)
            z = make_zone(center, idx)
            if z is not None:
                zones.append(z)
                idx += 1
    # Last resort (every flank/mouth spot collided): corners nearest the seating, clear of
    # the TV sightline - but RE-FACED toward the group so a chair never faces a wall.
    if not zones:
        corner_zones = _corner_spots(
            analysis, placed, "accent_chair", CHAIR, max_zones=2,
            near=group_front, near_radius=analysis.diag_cm, reasons=[R_CONVERSATION_ANGLE],
        )
        if corridor is not None:
            corner_zones = [z for z in corner_zones if z.polygon.intersection(corridor).area < 600.0]
        for z in corner_zones:
            cen = z.polygon.centroid
            toward = unit(*sub2(gc, (cen.x, cen.y)))
            z.rotation_deg = rotation_for_normal(toward)
            z.fwd = toward
        zones = corner_zones
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


def _beside_seating_spots(
    analysis: RoomAnalysis, placed: list[PlacedProduct], category: str,
    size: float, reasons: list[str], score: float,
) -> list[ZoneData]:
    """A floor lamp / accent piece LEVEL BESIDE a seat - next to a sofa arm or an accent
    chair, in the open side (not in front of the seats, not behind, not in the TV view).
    A spot a side table already holds is skipped (the piece comes back clipped), so the
    item finds a genuinely free space beside the seating - else it falls to a corner."""
    seats = [(i, p) for i, p in placed if p.category in ("sofa", "accent_chair")]
    blockers = _placed_blockers(placed, buffer_cm=6.0)
    corridor = _tv_view_corridor(analysis, placed)  # a floor lamp must not block the TV
    placed_here = [(i.x, i.y) for i, p in placed if p.category == category]
    zones: list[ZoneData] = []
    idx = 0
    for item, product in seats:
        w = width_axis(item.rotation_deg)
        for side in (-1.0, 1.0):
            pt = add((item.x, item.y), w, side * (product.width_cm / 2.0 + size / 2.0 + 10.0))
            if any(dist(pt, c) < size + 30.0 for c in placed_here):
                continue  # already a lamp/plant here - spread them out
            rect = item_polygon(pt[0], pt[1], size, size, 0)
            clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
            piece = largest_piece(clipped)
            # require the spot MOSTLY clear: a side table at this seat-end clips it heavily
            if piece is None or piece.area < size * size * 0.6:
                continue
            if corridor is not None and piece.intersection(corridor).area > 300.0:
                continue  # would sit in the TV->sofa sightline
            # a lamp beside a small accent chair reads better than one stranded by a wide
            # sofa whose ends are taken; nudge chair-side spots slightly higher.
            bonus = 0.05 if product.category == "accent_chair" else 0.0
            zones.append(
                _frame_zone(
                    category, 200 + idx, piece, score - 0.04 * side + bonus,
                    0.0, pt, (0.0, 1.0), (1.0, 0.0), size, size, reasons, "beside_seat", kind="free",
                )
            )
            idx += 1
    return _rank(zones, limit=2)


def _lighting_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    near = None
    secondary: list[ZoneData] = []
    if sofa is not None:
        item, product = sofa
        f = front_vector(item.rotation_deg)
        near = add((item.x, item.y), f, product.depth_cm / 2.0)
        # a modern family room wants the floor lamp BESIDE the seating (a reading lamp by
        # the sofa), not parked in a corner - so score it above the corner spots. The 1st
        # lamp lands beside the seating; only a 2nd spills to a corner.
        secondary = _beside_seating_spots(analysis, placed, "lighting", 40.0, [R_BESIDE_SEATING], 1.05)
    # all corners, ranked by proximity to the seating (no hard radius cut-off)
    zones = _corner_spots(
        analysis, placed, "lighting", 55.0, max_zones=8,
        near=near, near_radius=analysis.diag_cm if near else 0.0, reasons=[R_CORNER_LIGHT],
    )
    if analysis.area_cm2 >= BIG_ROOM_CM2:
        zones += _long_wall_spots(analysis, placed, "lighting", 55.0, [R_CORNER_LIGHT])
    zones += secondary
    if not zones:
        zones = _corner_spots(analysis, placed, "lighting", 55.0, max_zones=4, reasons=[R_CORNER_LIGHT])
    return _rank(_drop_window_blocking(analysis, zones), limit=4)


def _storage_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    s = stats.get("storage", {})
    depth = s.get("max_d", 45.0) + 6.0
    min_w = min(s.get("min_w", 80.0), 80.0)
    blockers = _placed_blockers(placed)
    cands = _wall_band_candidates(analysis, depth, min_w, use_solid=True, blockers=blockers)
    if not cands:
        return []
    corridor = _tv_view_corridor(analysis, placed)  # a tall cabinet must not block the TV

    def cov(c: _BandCandidate) -> float:
        return c.piece.intersection(corridor).area / max(c.piece.area, 1e-9) if corridor is not None else 0.0

    # whenever any wall keeps storage out of the TV->sofa sightline, use only those;
    # fall back to all walls (penalised) in a tiny room where every option clips it.
    clear = [c for c in cands if cov(c) <= 0.30]
    usable = clear if clear else cands
    max_extent = max(c.extent for c in usable)
    zones: list[ZoneData] = []
    for i, cand in enumerate(usable):
        score = (
            0.7 * (cand.extent / max_extent)
            + 0.3 * _entry_distance_norm(analysis, cand.piece)
            - 0.6 * cov(cand)
        )
        zones.append(_band_zone(analysis, cand, "storage", i, score, [R_REMAINING_WALL], depth))
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
    if near is not None:
        # accent piece beside the seating - a secondary position alongside the corners
        zones += _beside_seating_spots(analysis, placed, "decor", 45.0, [R_BESIDE_SEATING], 0.62)
    return _rank(_drop_window_blocking(analysis, zones), limit=6)


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

# the four pieces a family room must have; everything else is "soft" - placed only
# when a clean spot exists, otherwise skipped (quality-gated, see drop_cramped_zones).
ESSENTIAL_CATEGORIES = frozenset({"sofa", "tv_unit", "rug", "coffee_table"})


def drop_cramped_zones(
    analysis: RoomAnalysis, zones: list[ZoneData], max_walkway: float = 0.20
) -> list[ZoneData]:
    """Keep only zones that sit clear of the walking paths - used to quality-gate
    non-essential items so a 2nd chair / extra decor is SKIPPED rather than jammed
    into a circulation route when the room is tight."""
    return [z for z in zones if _corridor_overlap_ratio(analysis, z.polygon) <= max_walkway]


def zones_for_category(
    category: str,
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    stats: CategoryStats,
    n_planned: int = 1,
) -> list[ZoneData]:
    """`n_planned` is how many of this category the plan calls for; only the sofa
    generator uses it (to centre an L/U cluster rather than just the primary sofa)."""
    if category == "sofa":
        return _sofa_zones(analysis, placed, stats, n_planned=n_planned)
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
        lo_c, hi_c = a + half + 2.0, b - half - 2.0
        if zone.anchor_t is not None and hi_c > lo_c:
            # bias toward a wall end (corner-tight L return) instead of centring
            mid = lo_c + max(0.0, min(1.0, zone.anchor_t)) * (hi_c - lo_c)
        else:
            mid = (a + b) / 2.0
            if b - a > product.width_cm + 4.0:
                mid = min(max(mid, lo_c), hi_c)
        center = add(wall.point_at(mid), wall.normal, product.depth_cm / 2.0 + 4.0 + zone.float_cm)
        return Pose(x=round(center[0], 1), y=round(center[1], 1), rotation_deg=zone.rotation_deg)

    if zone.kind == "frame" and zone.origin is not None and zone.fwd is not None:
        center = add(zone.origin, zone.fwd, product.depth_cm / 2.0)
        return Pose(x=round(center[0], 1), y=round(center[1], 1), rotation_deg=zone.rotation_deg)

    if zone.kind == "side" and zone.origin is not None and zone.fwd is not None:
        center = add(zone.origin, zone.fwd, product.width_cm / 2.0 + 2.0)
        return Pose(x=round(center[0], 1), y=round(center[1], 1), rotation_deg=zone.rotation_deg)

    if zone.place_at_origin and zone.origin is not None:
        # honour the intended centre (e.g. an L/U arm sofa) so a clipped piece's centroid
        # can't shift the item toward its neighbour and overlap it.
        return Pose(x=round(zone.origin[0], 1), y=round(zone.origin[1], 1), rotation_deg=zone.rotation_deg)
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
