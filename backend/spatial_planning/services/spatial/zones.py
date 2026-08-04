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

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from spatial_planning.models.geometry import PlacedItem, Pose
from spatial_planning.models.products import SMALL_MEDIUM_MAX_CM2, Product, placement_group
from spatial_planning.services.spatial.core import RoomAnalysis, WallData, ZoneData
from spatial_planning.services.spatial.geometry_utils import (
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
R_SEPARATE_DINING_ZONE = "separate_dining_zone"
R_FACES_DINING_TABLE = "faces_dining_table"
R_LONG_CLEAR_WALL = "long_clear_wall"
R_KEEP_CENTER_OPEN = "keep_center_open"
R_MAXIMIZE_SEATING = "maximize_seating"
# Bedroom
R_HEADBOARD_TO_WALL = "headboard_to_wall"
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


def _door_far_anchor(analysis: RoomAnalysis, cand: "_BandCandidate", near_cm: float = 130.0) -> float | None:
    """An `anchor_t` that pulls a wall piece toward the end of its wall FARTHER from the nearest door -
    so a piece on a wall whose END meets a door (a door on THIS or an adjacent wall, whose swing reaches
    the corner) slides DOWN the wall, clear of the entry, instead of centring by the door. Returns None
    when no door is near either end (then the piece centres as usual) or when a door sits mid-run (no
    clearly-far end). The anchor_pose clamp turns this into "hug the far end"."""
    if not analysis.swing_arcs:
        return None
    swing = unary_union(list(analysis.swing_arcs.values()))
    w = cand.wall
    lo_pt = w.point_at(cand.lo)
    hi_pt = w.point_at(cand.hi)
    d_lo = swing.distance(Point(lo_pt[0], lo_pt[1]))
    d_hi = swing.distance(Point(hi_pt[0], hi_pt[1]))
    if min(d_lo, d_hi) > near_cm:
        return None  # no door near either end of this run -> centre as before
    if abs(d_lo - d_hi) < 40.0:
        return None  # door roughly equidistant (mid-run) -> no clearly-far end to hug
    return cand.hi if d_lo < d_hi else cand.lo  # hug the end FAR from the door


def _vanity_clear_anchor(cand: "_BandCandidate", bed_poly, gap_cm: float = 85.0) -> float | None:
    """An `anchor_t` that slides the DRESSING TABLE along its wall just far enough that its stool (pulled
    up in front, centred) clears the bed - the vanity's wall often meets the bed at a corner, and a centred
    vanity's stool then falls inside the bed's keep-clear and is dropped. Keeps the vanity as CENTRAL as
    possible (never cornered): among the run positions whose centre sits `gap_cm` clear of the bed's SHADOW
    on the wall, returns the one NEAREST the run centre. None when the centred position already clears (bed
    not near this wall); the run END farthest from the bed when the shadow+gap covers the whole run."""
    if bed_poly is None:
        return None
    w = cand.wall
    coords = list(bed_poly.exterior.coords)
    # Only a bed CLOSE to this wall (perpendicular) can crowd a stool pulled up in front of it (~110 cm
    # deep). A bed on the OPPOSITE wall projects a SHADOW onto this wall yet sits metres away, so its stool
    # clears - don't shift the vanity for it (that would needlessly move / drop a 2nd-storage vanity).
    perp = min(dot(sub2((x, y), w.start), w.normal) for x, y in coords)
    if perp > 160.0:
        return None
    ts = [dot(sub2((x, y), w.start), w.dir) for x, y in coords]
    b0, b1 = min(ts), max(ts)
    lo, hi = cand.lo, cand.hi
    centre = (lo + hi) / 2.0
    if centre <= b0 - gap_cm or centre >= b1 + gap_cm:
        return None  # the centred vanity's stool already clears the bed -> centre as usual
    below_hi = b0 - gap_cm  # positions at/below this clear the bed on the low side
    above_lo = b1 + gap_cm  # positions at/above this clear it on the high side
    cands: list[float] = []
    if below_hi >= lo:
        cands.append(min(below_hi, hi))   # nearest-to-centre clear point on the low side
    if above_lo <= hi:
        cands.append(max(above_lo, lo))   # nearest-to-centre clear point on the high side
    if cands:
        return min(cands, key=lambda t: abs(t - centre))
    # The bed's shadow (+gap) covers the whole run: best effort - hug the end FARTHER from the bed.
    return lo if abs(lo - (b0 + b1) / 2.0) > abs(hi - (b0 + b1) / 2.0) else hi


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


# A seating group floats forward only if the strip it leaves BEHIND is a genuine walkway - at least
# a comfortable passage width. Below this the float just opens a dead, boxed-in sliver against the
# wall (the pocket the guest can't use), so the sofa hugs the wall instead and accepts a farther TV.
# (A true great room clears this easily - it floats ~200cm+ behind; a medium room clears ~100cm and
# stays wall-hugged.) This is what separates the legitimate great-room float from a dead back strip.
FLOAT_MIN_BACK_WALKWAY_CM = 120.0


# --- per-category generators -------------------------------------------------


def _sofa_zones(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    stats: CategoryStats,
    tv_requested: bool = True,
    side_shift_mode: str | None = None,
) -> list[ZoneData]:
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
        # Phase 4: this penalty ONLY exists to reserve a clear wall for the TV. When no TV was
        # REQUESTED (conversation-focal room) there is nothing to keep off the glass, so drop it
        # and let the sofa take the genuinely best wall (longest / facing the room), window or not.
        faced = min(analysis.walls, key=lambda ww: dot(cand.wall.normal, ww.normal))
        faces_window = any(o.kind == "window" for o in faced.openings)
        score = (
            0.40 * (cand.extent / max_extent)
            + 0.20 * (1.0 - 0.5 * win_ratio)
            + 0.20 * entry_norm
            + 0.20 * focal
            - 0.15 * corridor_ratio
            - (0.7 if (faces_window and tv_requested) else 0.0)
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
            want_float = max(0.0, facing_dist - tv_front_depth - TV_VIEWING_DISTANCE)
            # Float the group forward ONLY when doing so leaves a genuine WALKWAY behind the sofa
            # (>= a comfortable passage). Otherwise floating just opens a DEAD sliver boxed against
            # the wall - so the sofa hugs the wall and accepts a farther TV (honest) instead.
            if want_float >= FLOAT_MIN_BACK_WALKWAY_CM:
                float_cm = want_float
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
        # Great-room LATERAL shift: push the sofa toward one side wall so the opposite flank opens into a
        # usable block (see the constant docs). Direction: the end FARTHER from the door (keeps the deep
        # sofa clear of the entry), else the `lo` end (deterministic). Aiming at an extreme is safe -
        # anchor_pose clamps the centre to keep the sofa inside the run, so a wide sofa just hugs flush.
        anchor_t = None
        if side_shift_mode and analysis.area_cm2 >= GREAT_ROOM_MIN_CM2 and (cand.hi - cand.lo) - min_w > _SIDE_SHIFT_MIN_SLACK_CM:
            door_ts = [
                dot(sub2((arc.centroid.x, arc.centroid.y), cand.wall.start), cand.wall.dir)
                for arc in analysis.swing_arcs.values()
            ]
            mid_run = (cand.lo + cand.hi) / 2.0
            toward_lo = (sum(door_ts) / len(door_ts) > mid_run) if door_ts else True  # sit opposite the door
            # Always a BOUNDED shift: keep the primary centre this far off the near wall so the secondary
            # sofa (toward the wall) AND a companion chair still fit on the near flank - never jam it to
            # the wall (which stranded the chair).
            anchor_t = (cand.lo + _NEAR_FLANK_RESERVE_CM) if toward_lo else (cand.hi - _NEAR_FLANK_RESERVE_CM)
        zones.append(_band_zone(analysis, cand, "sofa", i, score, reasons, depth, float_cm=float_cm, anchor_t=anchor_t))
    return _rank(zones)


# Viewing geometry. A TV is comfortable ~2.5-4 m from the sofa. In a GREAT-ROOM the wall
# the sofa faces is farther than this, so the SEATING GROUP floats forward to a human
# viewing distance (see _sofa_zones) and the TV stays wall-mounted (rather than the TV
# floating out to meet a wall-glued sofa).
TV_VIEWING_DISTANCE = 330.0  # target gap: sofa front -> (wall-mounted) TV front
TV_WALL_TOO_FAR = 450.0  # facing-wall distance beyond which the seating floats forward toward the TV

# Great-room LATERAL shift: slide the WHOLE conversation group (sofa + TV, which follows the sofa's
# projection, + rug/coffee that anchor to its pose) sideways toward one side wall so the opposite flank
# opens into ONE contiguous block. The sofa<->TV DEPTH is untouched (the float is unchanged), only the
# along-wall position moves. Triggered by INTENT (see orchestrator `_side_shift_mode`), NOT by area alone:
# The shift is always BOUNDED (see orchestrator `_side_shift_mode`): the group slides toward one side but
# keeps `_NEAR_FLANK_RESERVE_CM` off the near wall, so the secondary sofa (which hugs the wall) AND a
# companion chair still fit on the near flank - nothing is jammed against the wall or stranded. Only fires
# in a great room with real lateral slack; small/medium rooms stay centred (byte-identical goldens).
GREAT_ROOM_MIN_CM2 = 400_000.0  # 40 m² - floor for the lateral shift
MASSIVE_ROOM_MIN_CM2 = 600_000.0  # 60 m² - floor for the multi-zone treatment (reading-nook rug, etc.): a big
#                                   room reads as several tight rug-anchored clusters, not one group in a void
_SIDE_SHIFT_MIN_SLACK_CM = 120.0  # need at least this much run beyond the sofa before it's worth shifting
_NEAR_FLANK_RESERVE_CM = 280.0  # keep the primary centre this far off the near wall so a return + chair still fit
SOFA_FRONT_CM = 95.0  # a typical sofa's front distance from its back wall (the exact sofa isn't chosen yet)
TV_DOOR_CLEAR_CM = 25.0  # keep the TV unit this clear of a door swing on its wall (see _tv_zones)
CONSOLE_TV_CLEAR_CM = 40.0  # keep a living console this clear of the TV unit at a shared wall corner (_storage_zones)
WARDROBE_SIDE_TABLE_CLEAR_CM = 40.0  # slide a bedroom wardrobe this clear of a nightstand at a shared corner


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


def _bedroom_tv_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    """A bedroom TV unit on the wall the bed FACES (opposite the headboard), centred on the bed so it's
    watchable from it. Placed ONLY on that facing wall - if it's blocked (a wardrobe / desk / dresser
    took it) or has no clear solid run, the TV is skipped (it yields to the wall pieces, CLAUDE.md 5.2
    drop priority). No bed -> no TV."""
    bed = _find_placed(placed, "bed")
    if bed is None:
        return []
    s = stats.get("tv_unit", {})
    depth = s.get("max_d", 48.0) + 8.0
    min_w = s.get("min_w", 120.0)
    blockers = _placed_blockers(placed, buffer_cm=30.0)  # bedroom margin off other pieces
    cands = _wall_band_candidates(analysis, depth, min_w * 0.9, use_solid=True, blockers=blockers, door_clearance=_BEDROOM_DOOR_CLEAR_CM)
    if not cands:
        cands = _wall_band_candidates(analysis, depth, 90.0, use_solid=True, blockers=blockers, door_clearance=_BEDROOM_DOOR_CLEAR_CM)
    if not cands:
        return []
    # Trim each band's RUN clear of adjacent-wall furniture (a wardrobe / desk hugging the next wall) - the
    # extent over-reports when only a corner is clipped, so a wide TV would otherwise overhang that piece.
    if blockers is not None and not blockers.is_empty:
        cands = _trim_band_extent(cands, analysis, depth, blockers, min_w * 0.9)
    if not cands:
        return []
    item, product = bed
    f = front_vector(item.rotation_deg)  # headboard -> foot (into the room)
    bed_front = add((item.x, item.y), f, product.depth_cm / 2.0)
    # ONLY the wall the bed faces (its inward normal opposes the bed's front): a bedroom TV must be
    # watchable from the bed, so a non-facing wall is never used - the TV yields instead.
    facing = [c for c in cands if dot(c.wall.normal, f) < -0.7]
    if not facing:
        return []
    max_extent = max(c.extent for c in facing)
    zones: list[ZoneData] = []
    for i, cand in enumerate(facing):
        d_wall = first_boundary_hit(analysis.polygon, bed_front, f)
        dist_score = 1.0 if 200.0 <= d_wall <= 500.0 else 0.5
        # Centre the TV on the BED: project the bed centre onto this wall, then carve a band SYMMETRIC
        # about that projection. A TV placed in a symmetric band is always centred on the bed - it can
        # NEVER clamp off-centre (the old code left the anchor to clamp inside the full run, which shoved
        # the TV off the bed when the bed's line sat near a run end / off a window-split wall). If the
        # symmetric half-width can't hold even a minimum TV, the bed can't be watched from a centred TV on
        # this wall, so it's SKIPPED (the TV yields - CLAUDE.md 5.2 - rather than render off-centre).
        proj = dot(sub2(bed_front, cand.wall.start), cand.wall.dir)
        hw = min(proj - cand.lo, cand.hi - proj)  # symmetric half-width available about the bed centre
        if 2.0 * hw < min_w * 0.9:
            continue  # no room for a TV centred on the bed here -> yield (never off-centre)
        a, b = proj - hw, proj + hw
        sym_quad = quad(
            add(cand.wall.point_at(a), cand.wall.normal, 2.0),
            add(cand.wall.point_at(b), cand.wall.normal, 2.0),
            add(cand.wall.point_at(b), cand.wall.normal, 2.0 + depth),
            add(cand.wall.point_at(a), cand.wall.normal, 2.0 + depth),
        )
        piece = sym_quad.intersection(cand.piece)  # keep the original clipping (door swing / OOB)
        if piece.is_empty or piece.area < 1_000.0:
            continue
        sym = _BandCandidate(wall=cand.wall, lo=a, hi=b, piece=piece, extent=2.0 * hw)
        score = 0.5 + 0.3 * dist_score + 0.2 * (min(2.0 * hw, max_extent) / max_extent)
        zones.append(_band_zone(analysis, sym, "tv_unit", i, score, [R_IDEAL_VIEWING_DIST], depth, anchor_t=proj))
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


def _free_zone_center(
    analysis: RoomAnalysis,
    category: str,
    size_w: float,
    size_d: float,
    center: tuple[float, float] | None = None,
) -> list[ZoneData]:
    """A free zone centred on the open area (default) or on an explicit `center` point
    (e.g. a bedroom rug centred on the bed so it grounds it, not the room)."""
    usable = largest_piece(analysis.usable_area)
    if usable is None:
        return []
    # Never request a footprint larger than the open area itself. Real catalogs carry huge
    # rugs (up to ~5x4 m); without this a giant rug would be selected and poke through the
    # walls in a normal room. Large rooms (e.g. majlis) are unaffected - the cap doesn't bind.
    minx, miny, maxx, maxy = usable.bounds
    size_w = max(60.0, min(size_w, (maxx - minx) - 30.0))
    size_d = max(60.0, min(size_d, (maxy - miny) - 30.0))
    if center is None:
        c = usable.centroid
        cx, cy = c.x, c.y
    else:
        cx, cy = center
    rect = item_polygon(cx, cy, size_w, size_d, 0).intersection(usable)
    piece = largest_piece(rect)
    if piece is None or piece.area < 2_000.0:
        return []
    anchor_label = "room_center" if center is None else "under_bed"
    return [
        _frame_zone(
            category, 0, piece, 0.6, 0.0, (cx, cy), (0.0, 1.0), (1.0, 0.0),
            size_d, size_w, [R_FLEXIBLE_SPOT], anchor_label, kind="free",
        )
    ]


def _bedroom_rug_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    """A BIG bedroom rug brought FORWARD: only ~1/8 of the bed (its foot) sits on the rug, and the rest
    fans out INTO THE ROOM in front of the foot - a generous area rug you step onto, the bed mostly OFF
    it. Anchored at its NEAR EDGE (a FRAME zone, so anchor_pose keeps that edge fixed): the 1/8 coverage
    holds whatever rug size the selector picks. Wide side reveal; clamped to the room so it never
    overflows. No bed (the rug depends on it, so rare) -> a room-centred rug."""
    bed = _find_placed(placed, "bed")
    if bed is None:
        minx, miny, maxx, maxy = analysis.polygon.bounds
        return _free_zone_center(analysis, "rug", (maxx - minx) * 0.62, (maxy - miny) * 0.62)
    item, product = bed
    f = front_vector(item.rotation_deg)   # headboard -> foot (into the room)
    wax = width_axis(item.rotation_deg)
    d, bw = product.depth_cm, product.width_cm
    bed_cover = d / 8.0
    # NEAR edge of the rug: on the bed's centre line, at the foot MINUS 1/8 of the bed.
    near = add((item.x, item.y), f, d / 2.0 - bed_cover)
    fwd_len = min(bed_cover + 0.6 * d + 90.0, first_boundary_hit(analysis.polygon, near, f) - 20.0)
    if fwd_len < 60.0:
        return []
    lat_room = min(first_boundary_hit(analysis.polygon, near, wax),
                   first_boundary_hit(analysis.polygon, near, (-wax[0], -wax[1])))
    lat_len = min(bw + 150.0, 2.0 * (lat_room - 15.0))  # ~75 cm reveal each side, clamped to the room
    if lat_len < 80.0:
        return []
    rect = quad(
        add(near, wax, -lat_len / 2.0), add(near, wax, lat_len / 2.0),
        add(add(near, wax, lat_len / 2.0), f, fwd_len),
        add(add(near, wax, -lat_len / 2.0), f, fwd_len),
    )
    piece = largest_piece(rect.intersection(analysis.polygon))
    if piece is None or piece.area < 2_000.0:
        return []
    return [_frame_zone("rug", 0, piece, 0.9, item.rotation_deg, near, f, wax, fwd_len, lat_len, [R_ANCHORS_SEATING], "bed_foot")]


# A rug reaches this far UNDER the front edge of the seating pieces it anchors: the front legs sit ON
# the rug, the back legs stay OFF (the classic "front legs on" rule). Applied as an inset from the
# conversation group's outer footprint on every bounded side.
_RUG_FRONT_LEGS_UNDER_CM = 55.0


def _rug_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    s = stats.get("rug", {})
    sofa = _find_placed(placed, "sofa")
    if sofa is None:
        return _free_zone_center(analysis, "rug", s.get("max_w", 300.0), s.get("max_d", 240.0))

    # BASELINE (primary sofa only) - byte-identical to the pre-group behaviour. This is what the LEGACY
    # planner (which places the rug when only the primary sofa exists) and a lone-sofa room always get.
    item, product = sofa
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    sofa_front = add((item.x, item.y), f, product.depth_cm / 2.0)
    forward_clear = first_boundary_hit(analysis.polygon, sofa_front, f)
    fwd_len = min(forward_clear - 30.0, 260.0)
    if fwd_len < 80.0:
        fwd_len = max(forward_clear - 10.0, 60.0)
    lat_len = product.width_cm + 70.0
    lat_center = 0.0  # lateral offset from the primary sofa's centre line

    # EXPAND to the whole CONVERSATION GROUP ("front legs on") once the returns/flanking chairs exist -
    # i.e. in the recipe, which now places the rug AFTER the seating group. Dining chairs aren't placed
    # yet, so accent chairs here are the flanking (conversation) ones. Never shrinks below the baseline.
    group = [(it, pr) for it, pr in placed
             if placement_group(pr.category) == "sofa" or pr.category in ("accent_chair", "chair")]
    if len(group) > 1:
        U = _RUG_FRONT_LEGS_UNDER_CM
        fmax = wmin = wmax = None
        for it2, pr2 in group:
            poly2 = item_polygon(it2.x, it2.y, pr2.width_cm, pr2.depth_cm, it2.rotation_deg)
            for px, py in poly2.exterior.coords:
                fv = (px - item.x) * f[0] + (py - item.y) * f[1]
                wv = (px - item.x) * w[0] + (py - item.y) * w[1]
                fmax = fv if fmax is None else max(fmax, fv)
                wmin = wv if wmin is None else min(wmin, wv)
                wmax = wv if wmax is None else max(wmax, wv)
        f_back = product.depth_cm / 2.0 - 25.0
        # forward: reach the group's forward extent, front legs of the facing seating on (bounded by the walkway)
        group_fwd = (fmax - U) - f_back
        fwd_len = max(fwd_len, min(group_fwd, forward_clear - 30.0))
        # lateral: cover the group's lateral span, flanks' front legs on - never narrower than the baseline
        group_lat = (wmax - wmin) - 2.0 * U
        if group_lat > lat_len:
            lat_len = group_lat
            lat_center = (wmin + wmax) / 2.0

    near = add(add(sofa_front, f, -25.0), w, lat_center)  # rug slides 25 cm under the primary sofa front
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


def _nook_rug_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats) -> list[ZoneData]:
    """A SECOND, SMALLER rug that anchors the reading nook (under the chaise, extending a bit in front). Only
    in a MASSIVE room (>= 60 m2) and only once the chaise is placed - it turns the lone chaise into a proper
    zone. Aligned to the chaise, sized to it (compact, so the selector picks a smaller rug than the main one -
    'coordinate, don't match'); the palette makes both harmonise. Walkable, so it disturbs nothing."""
    if analysis.area_cm2 < MASSIVE_ROOM_MIN_CM2:
        return []
    chaise = _find_placed(placed, "chaise")
    if chaise is None:
        return []
    item, product = chaise
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    # Rug frame: back edge at the chaise's back, extending forward past its front so the rug reads under the
    # chaise + a strip of floor in front (where the feet / side table sit). Laterally a touch wider than it.
    lat_len = product.width_cm + 30.0
    fwd_len = product.depth_cm + 90.0
    near = add((item.x, item.y), f, -product.depth_cm / 2.0)  # rug back edge = chaise back
    inner = analysis.polygon.buffer(-8.0)
    rect = quad(
        add(near, w, -lat_len / 2.0),
        add(near, w, lat_len / 2.0),
        add(add(near, w, lat_len / 2.0), f, fwd_len),
        add(add(near, w, -lat_len / 2.0), f, fwd_len),
    )
    piece = largest_piece(rect.intersection(inner if not inner.is_empty else analysis.polygon))
    if piece is None or piece.area < 4_000.0:
        return []
    return [
        _frame_zone(
            "rug", 0, piece, 0.9, item.rotation_deg, near, f, w, fwd_len, lat_len,
            [R_FRONT_LEGS_ON_RUG], "chaise_nook",
        )
    ]


def _nook_satellite_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats, category: str
) -> list[ZoneData]:
    """A small accent (floor lamp / side table) placed BESIDE the chaise to complete the reading nook. Massive
    rooms only, chaise placed. Tries the chaise's two ENDS (preferring the one toward the room corner, where a
    reading lamp belongs), just off the chaise's long side, at a couple of forward offsets - the first spot that
    sits fully inside the room and clear of every placed piece wins. Runs after the chaise + nook rug, and the
    lamp runs after the side table, so each avoids what the others already took (via the placed blockers)."""
    if analysis.area_cm2 < MASSIVE_ROOM_MIN_CM2:
        return []
    chaise = _find_placed(placed, "chaise")
    if chaise is None:
        return []
    item, product = chaise
    w = width_axis(item.rotation_deg)
    f = front_vector(item.rotation_deg)
    s = stats.get(category, {})
    sw = min(s.get("max_w", 55.0), 65.0)
    sd = min(s.get("max_d", 50.0), 60.0)
    blockers = _placed_blockers(placed, buffer_cm=5.0)
    inner = analysis.polygon.buffer(-6.0)
    rc = analysis.polygon.centroid

    def _end_pt(sign: float) -> Vec:
        return (item.x + w[0] * sign * product.width_cm / 2.0, item.y + w[1] * sign * product.width_cm / 2.0)

    # A nook satellite (side table / floor lamp) already at one chaise END makes that end OCCUPIED, so
    # the current satellite prefers the OPPOSITE end - the side table and floor lamp end up at opposite
    # ends of the chaise, not clustered on the same side. (The side table runs first, the lamp second.)
    occupied: set[float] = set()
    for it2, pr2 in placed:
        if placement_group(pr2.category) not in ("side_table", "lighting"):
            continue
        along = (it2.x - item.x) * w[0] + (it2.y - item.y) * w[1]   # position along the chaise width
        perp = abs((it2.x - item.x) * f[0] + (it2.y - item.y) * f[1])  # in front of / behind the chaise
        if product.width_cm / 2.0 - 25.0 < abs(along) < product.width_cm / 2.0 + 90.0 and perp < 110.0:
            occupied.add(1.0 if along > 0 else -1.0)  # a satellite is at this chaise end
    # UNOCCUPIED end first (split the two satellites to opposite ends), then the corner side (farther
    # from the room centre - where a floor lamp reads best).
    ends = sorted(
        (1.0, -1.0),
        key=lambda sign: (0 if sign in occupied else 1, dist(_end_pt(sign), (rc.x, rc.y))),
        reverse=True,
    )
    for sign in ends:
        for fwd in (0.0, 30.0, -25.0, 60.0):
            cx = item.x + w[0] * sign * (product.width_cm / 2.0 + sw / 2.0 + 6.0) + f[0] * fwd
            cy = item.y + w[1] * sign * (product.width_cm / 2.0 + sw / 2.0 + 6.0) + f[1] * fwd
            poly = item_polygon(cx, cy, sw, sd, item.rotation_deg)
            if inner.contains(poly) and (blockers.is_empty or not poly.intersects(blockers)):
                return [_frame_zone(category, 0, poly, 0.7, item.rotation_deg, (cx, cy), f, w, sd, sw, [R_FLEXIBLE_SPOT], "chaise_nook", kind="free")]
    return []


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
    # Keep the side table OFF the door side of the sofa - a table by the entry reads wrong. When no
    # companion seat pins the side, steer it to the side AWAY from the door instead of the neutral
    # default. (With a companion seat present the seat side wins; it's typically the door-free side.)
    door_side = 0.0
    door_pts = [sw.centroid for sw in analysis.swing_arcs.values()]
    if door_pts:
        dv = [dot(sub2((p.x, p.y), (item.x, item.y)), w) for p in door_pts]
        if min(dv) > 20.0:
            door_side = 1.0
        elif max(dv) < -20.0:
            door_side = -1.0
    blockers = _placed_blockers(placed)
    # Furniture-clearance gate: the single side table must keep a sensible margin from OTHER placed
    # furniture (e.g. a chaise-lounge occupying a sofa flank), not merely abut the sofa it serves.
    # Build a clearance region from every placed non-walkable item EXCEPT the sofa(s) the table
    # flanks, then reject a flank whose predicted table pose falls within the buffer of that region.
    # If the preferred flank is crowded but the other is clear, the clear flank wins (its lower score
    # keeps it a fallback); if BOTH flanks are crowded, no zone is returned and the (opt-in) side
    # table is skipped - it yields to the higher-priority piece already there.
    FURNITURE_CLEAR_CM = 20.0
    rep = stats.get("side_table", {})
    rep_half = max(rep.get("max_w", 70.0), rep.get("max_d", 70.0)) / 2.0
    # Keep the side table off the DOOR as well as off other furniture: a table flush to (or inside)
    # the door swing reads wrong and blocks the entry. Fold every door swing into the same clearance
    # region so the flank whose predicted table pose falls within FURNITURE_CLEAR_CM of a swing is
    # rejected - the table then takes the other (clear) flank, or is skipped if neither is clear.
    clear_polys = [
        item_polygon(i.x, i.y, p.width_cm, p.depth_cm, i.rotation_deg)
        for i, p in placed
        if not p.is_walkable and placement_group(p.category) != "sofa"
    ]
    clear_polys += list(analysis.swing_arcs.values())
    clearance = unary_union(clear_polys) if clear_polys else Polygon()
    zones: list[ZoneData] = []
    for idx, side in enumerate((-1.0, 1.0)):
        origin = add((item.x, item.y), w, side * (product.width_cm / 2.0 + 4.0))
        rect = item_polygon(*add(origin, w, side * 35.0), 78.0, max(product.depth_cm, 80.0), item.rotation_deg)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        piece = largest_piece(clipped)
        if piece is None or piece.area < 1_500.0:
            continue
        # Predicted table centre for this flank (mirrors anchor_pose for a "side" zone). Bound the
        # table by a circle of radius rep_half; requiring centre-to-furniture >= buffer + rep_half
        # keeps the nearest table edge at least the buffer off any other furniture.
        center = add(origin, (w[0] * side, w[1] * side), rep_half + 2.0)
        if not clearance.is_empty and Point(center).distance(clearance) < FURNITURE_CLEAR_CM + rep_half:
            continue
        if target_side != 0.0:
            # Strongly prefer the companion-seat side; the other side stays only as a fallback
            # for when that side can't fit the table.
            score = 0.95 if side == target_side else 0.45
        elif door_side != 0.0:
            score = 0.9 if side == -door_side else 0.45  # away from the door
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


# The door-flank chair is dropped only when the SOFA (the whole conversation group's anchor) sits this
# close to the door swing - i.e. a compromised layout where the group is jammed by the entry (e.g. a
# wide room whose long walls are windowed, forcing the sofa onto a short wall by the door). Then a
# second chair on the door flank boxes in the walk-in path. In an OPEN layout (sofa well clear of the
# door, e.g. on a long wall) the group isn't crowding the entry, so BOTH flanks are kept. Per-chair
# distance can't tell the two apart (the chair to keep can sit closer to the door than the one to drop);
# the anchor's proximity is what marks the crowded layout. (Compromised layouts sit ~20-30 cm off the
# swing; open long-wall layouts ~230 cm - so this sits safely in the middle of that gap.)
_GROUP_NEAR_DOOR_CM = 120.0


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
    # Steer a single chair to the door-FREE flank. The console is now placed AFTER the chair (recipe:
    # companion_seating -> storage), so the chair claims the side away from the entry first; the console
    # then takes the remaining door-side wall. `door_side` is the flank (+1/-1 along the sofa's width
    # axis) the door swing sits on, or 0 if it isn't clearly to one side (door behind/in front of the sofa).
    door_side = 0.0
    door_pts = [sw.centroid for sw in analysis.swing_arcs.values()]
    if door_pts:
        dv = [dot(sub2((p.x, p.y), (item.x, item.y)), w) for p in door_pts]
        if min(dv) > 20.0:
            door_side = 1.0
        elif max(dv) < -20.0:
            door_side = -1.0
    # Is the whole conversation group jammed by the entry? (sofa anchor near the door swing). Only then
    # is a second chair on the door flank dropped - see `_GROUP_NEAR_DOOR_CM`.
    sofa_poly = item_polygon(item.x, item.y, product.width_cm, product.depth_cm, item.rotation_deg)
    group_near_door = bool(analysis.swing_arcs) and min(
        sofa_poly.distance(arc) for arc in analysis.swing_arcs.values()
    ) < _GROUP_NEAR_DOOR_CM
    # A SECONDARY sofa (L-return / U-shape return) already occupies a flank of the primary; a companion
    # chair on that same flank crams into the L's inside corner, touching the return. Treat the return's
    # flank as crowded and prefer the OPPOSITE, open flank - the chair only falls back onto a return flank
    # if the open one can't seat it. (Mirrors the door-flank hold-back below.)
    secondaries = [(sit, spr) for sit, spr in placed if placement_group(spr.category) == "sofa" and sit is not item]

    def _return_on(side_sign: float) -> bool:
        return any(
            dot(sub2((sit.x, sit.y), (item.x, item.y)), (side_sign * w[0], side_sign * w[1])) > 20.0
            for sit, _spr in secondaries
        )
    # cap how far FORWARD (toward the TV) the chair may sit, so it stays clear of the TV
    tv_front = add((tv[0].x, tv[0].y), front_vector(tv[0].rotation_deg), tv[1].depth_cm / 2.0)
    max_fwd_extra = min(80.0, dot(sub2(tv_front, (item.x, item.y)), f) - product.depth_cm / 2.0 - CHAIR_HALF - 60.0)
    zones = []
    door_side_zones = []  # the flank the door opens onto - a chair here crowds the entry (fallback only)
    for idx, side in enumerate((-1.0, 1.0)):
        wall_dist = first_boundary_hit(analysis.polygon, (item.x, item.y), (side * w[0], side * w[1]))
        # No room BESIDE the sofa on this flank? (the sofa's side edge sits almost against the wall -
        # e.g. a great-room group shifted hard to this side.) Placing a chair here can't sit beside the
        # group; the old clamp would shove it forward into a FLOATING position off the sofa's corner.
        # Skip the flank instead - the chair takes the open flank, or is dropped (never floated).
        if wall_dist - product.width_cm / 2.0 < CHAIR_HALF + 20.0:
            continue
        # Bring the chair FLUSH to the conversation group: its inner edge touches the sofa's side line
        # (and the carpet edge), forming a tight group - not stranded against the far side wall. A 2 cm
        # hair of clearance keeps it off the sofa itself. Capped by the wall so a small room (wall nearer
        # than that) still tucks it against the wall rather than into the sofa.
        close_lat = product.width_cm / 2.0 + CHAIR_HALF + 2.0
        lat = min(close_lat, wall_dist - CHAIR_HALF - 14.0)
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
        z = _frame_zone(
            "accent_chair", idx, piece, 0.8 - 0.2 * corridor_pen, rotation,
            center, toward, w, 100.0, 100.0,
            [R_CONVERSATION_ANGLE], "beside_seating", kind="free",
        )
        # Drop a chair on the door flank ONLY in a group-jammed-by-the-entry layout (`group_near_door`):
        # there a second door-flank chair boxes in the walk-in path. Hold it back (use it only if the
        # door-FREE flank can't seat a chair, so the room isn't left chairless). In an open layout both
        # flanks are kept.
        crowds_entry = group_near_door and door_side != 0.0 and side == door_side
        crowds = crowds_entry or _return_on(side)  # keep the chair off the door flank AND the return flank
        (door_side_zones if crowds else zones).append(z)
    if not zones:
        zones = door_side_zones
    # A living-room accent chair is COMPANION seating - it only belongs BESIDE the sofa (a
    # conversation group). If neither flank is available it is simply SKIPPED - NO corner fallback: a
    # chair marooned in a corner isn't a living-room grouping (that's a bedroom reading-nook idea). The
    # template layer instead prefers a wall that CAN group the chair, and falls to a clean single sofa
    # only when no wall can.
    return _rank(zones, limit=2)


def _return_sofa_zone_floor(store_category: str = "2-seater-sofa") -> tuple[float, float]:
    """Minimum (width, depth) the return-sofa zone must reach to fit a REAL sofa of `store_category`
    (default a 2-seater), derived from the CATALOG so it needs no per-style magic constant and
    self-adjusts to any catalog. The WIDTH floor is the WIDEST of each style's NARROWEST such sofa:
    whatever style narrows the pool, its slimmest fitting sofa still fits (e.g. Islamic's only 2-seaters
    are 170cm, so a 140cm 'Islamic' primary must not cap the zone at 140). The DEPTH floor is the deepest.
    Falls back to sane per-size defaults when the catalog has no rows tagged with that store category (the
    fixture catalog), keeping the goldens unchanged for the 2-seater default."""
    from spatial_planning.models.style_metadata import STYLES
    from spatial_planning.services.catalog.repository import get_repository

    matches = [p for p in get_repository().in_category("sofa") if p.category == store_category]
    if not matches:  # fixture catalog has no store-category sofas -> sane defaults per size
        return (210.0, 115.0) if store_category == "3-seater-sofa" else (170.0, 110.0)
    per_style_min = [
        min(p.width_cm for p in matches if st in p.styles) for st in STYLES if any(st in p.styles for p in matches)
    ]
    floor_w = max(per_style_min) if per_style_min else max(p.width_cm for p in matches)
    floor_d = max(p.depth_cm for p in matches)
    return floor_w, floor_d


# A conversation group tops out at the primary + up to this many RETURN sofas (a U of 3 sofas). The
# `until_target` fill loop only reaches the 2nd return when the seat target still isn't met AND the free
# flank genuinely fits - so a modest gap still resolves to a single L-return ("an L is a pair") and small
# rooms (below the area guard) get none.
MAX_RETURN_SOFAS = 2


def _l_return_sofa_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats,
    return_category: str = "2-seater-sofa",
) -> list[ZoneData]:
    """A perpendicular RETURN sofa at one end of the primary, forming an L (or, on the free flank of an
    existing return, a U). Sized to `return_category` (the fill loop passes 3-seater vs 2-seater by gap).

    Fires only when there is genuinely clear room for the return at a free front corner of the PRIMARY -
    so small rooms yield nothing (the caller falls back to accent chairs). Returns the viable side(s)
    best-first (the more open, door-far side wins). Empty once the primary already carries the max number
    of returns (`MAX_RETURN_SOFAS`)."""
    sofas = [(i, p) for i, p in placed if placement_group(p.category) == "sofa"]
    if not (1 <= len(sofas) <= MAX_RETURN_SOFAS):  # need a primary; cap the U at primary + MAX returns
        return []
    if analysis.area_cm2 < SMALL_MEDIUM_MAX_CM2:  # match the 3-seater threshold (24 m2): a room big
        return []
    item, product = sofas[0]  # the PRIMARY is placed first; returns follow on its flanks
    f = front_vector(item.rotation_deg)  # primary faces the TV / conversation
    w = width_axis(item.rotation_deg)
    hw, hd = product.width_cm / 2.0, product.depth_cm / 2.0
    # The return zone must fit a REAL 2-seater. Never let an abnormally narrow/shallow primary (e.g. a
    # mislabeled 140x80cm "3-seater" a style/colour pick lands on) starve the zone so no standard
    # 2-seater fits - that silently drops the L-return and falls back to a small-room accent chair.
    # Floor BOTH width and depth at CATALOG-DERIVED 2-seater dimensions (see _return_sofa_zone_floor -
    # no per-style magic constant; self-adjusts). No-op for a normal wide primary; rescues a small one.
    # NB the WIDTH (ret_w) deliberately tracks the primary so the return sits WELL FORWARD down the arm,
    # leaving the flank beside the primary free for the companion accent chair (a flush return would
    # crowd the chair out and drop the seat count). The LATERAL offset below is tightened separately.
    floor_w, floor_d = _return_sofa_zone_floor(return_category)
    ret_w = max(product.width_cm, floor_w)
    ret_d = max(product.depth_cm, floor_d)
    # Lateral half-depth used to set how far OUT the return sits: the SELECTED return is typically much
    # shallower than floor_d (the DEEPEST catalogued 2-seater), so keying the offset on ret_d/2 sets the
    # loveseat further from the group / carpet than the accent chairs (which tuck flush). Estimate the
    # return's real half-depth from the PRIMARY sofa (sofas share a depth class), bounded by the zone.
    ret_half_lat = min(ret_d, max(product.depth_cm, 88.0)) / 2.0
    blockers = _placed_blockers(placed)
    swings = list(analysis.swing_arcs.values())
    # If the primary has been SHIFTED toward one side wall (great-room dining/U layout), the secondary
    # sofa should tuck to that NEAR wall - leaving the OPEN flank for the companion chair. Detect the
    # shift by asymmetric lateral wall distances; bias the return toward the near (smaller-distance) side.
    d_neg = first_boundary_hit(analysis.polygon, (item.x, item.y), (-w[0], -w[1]))
    d_pos = first_boundary_hit(analysis.polygon, (item.x, item.y), (w[0], w[1]))
    shifted = abs(d_neg - d_pos) > 60.0
    near_sign = -1.0 if d_neg < d_pos else 1.0
    zones: list[ZoneData] = []
    for idx, s in enumerate((-1.0, 1.0)):
        facing = (-s * w[0], -s * w[1])  # the return faces inward, across the L toward the primary
        # Beside the primary's END (past its width, in the open flank) and forward to its front
        # line: the return runs perpendicular along the sofa's facing axis, forming the L WITHOUT
        # reaching into the centred rug/coffee that sit in the L's opening. Its inner edge sits FLUSH to
        # the primary's side line (using ret_half_lat, the return's REAL half-depth, not the deep floor),
        # matching the accent chair (_accent_chair_zones `close_lat`) so the loveseat arms hug the group /
        # carpet just as tightly as the chairs do - never set further out (a gap between them and the rug).
        center = add(add((item.x, item.y), w, s * (hw + ret_half_lat + 2.0)), f, hd + ret_w / 2.0)
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
        if shifted and s == near_sign:
            score += 0.5  # a shifted group: pull the secondary sofa to the near wall (chair takes the open flank)
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
    # A tighter blocker set (real footprints + a small gap) to verify the accent's OWN footprint, centred
    # in the clear pocket, actually CLEARS its neighbours: the buffered clip can pass with 35% clear yet
    # leave the centred accent grazing a neighbour by < the 2% overlap tolerance (a plant on a dressing
    # table, a plant on a floor lamp). We skip such a corner rather than place a grazing accent.
    near_blockers = _placed_blockers(placed, buffer_cm=6.0)
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
        # The accent lands at the clear pocket's centroid (anchor_pose): ensure its footprint there
        # doesn't graze a neighbour, else SKIP this corner (it takes another corner, or is dropped) - a
        # corner accent must never overlap a real piece under the 2% tolerance.
        cc = piece.centroid
        if not near_blockers.is_empty and item_polygon(cc.x, cc.y, size * 0.62, size * 0.62, 0).intersects(near_blockers):
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
    # Keep a floor lamp a real clearance off other furniture (a lamp 8cm from the console looks
    # jammed): a 30cm blocker buffer, so it sits in a genuinely open corner near the seating rather
    # than crammed beside the console/side table. Too tight a corner just drops the lamp.
    zones = _corner_spots(
        analysis, placed, "lighting", 55.0, max_zones=3,
        near=near, near_radius=radius, reasons=[R_CORNER_LIGHT], blocker_buffer=30.0,
    )
    if not zones:
        zones = _corner_spots(analysis, placed, "lighting", 55.0, max_zones=3, reasons=[R_CORNER_LIGHT], blocker_buffer=30.0)
    return zones


def _storage_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats, room_type: str = "living_room",
    allow_small_console: bool = False, tv_requested: bool = True, store_category: str | None = None,
) -> list[ZoneData]:
    # SEPARATE handling per storage TYPE - they want different walls:
    #   console (living)     : a fully CLEAN wall (never behind the seating or across a path); optional.
    #   wardrobe (bedroom 1st): any clear wall; part of the set, sized to the room, never skipped on size.
    #   dressing-table (2nd) : a clean wall with room to SIT at it; may use the clear part of a door wall.
    already_storage = any(placement_group(pr.category) == "storage" for _it, pr in placed)
    target = ("dressing-table" if already_storage else "wardrobe") if room_type == "bedroom" else "console"

    # Small-room console skip: on the LEGACY path (allow_small_console=False) a console just crowds a
    # small/medium living room AND would float, so skip it on size (keeps the legacy golden intact).
    # On the RECIPE path (allow_small_console=True) the console ROLE only runs when the user opted it in
    # (Phase-1 checklist gating), so we DON'T size-skip - physical fit still governs: the clean-wall /
    # walkway / door / behind-seating rules below place the console only where a wall truly holds it,
    # else it's skipped cleanly -> the "didn't fit" notice.
    if target == "console" and analysis.area_cm2 < SMALL_MEDIUM_MAX_CM2 and not allow_small_console:
        return []
    s = stats.get("storage", {})
    depth = s.get("max_d", 45.0) + 6.0
    min_w = min(s.get("min_w", 80.0), 80.0)
    # Bedroom storage keeps a clear margin off the bed/other pieces (not the old 5cm); living console
    # keeps the tight buffer (its goldens hold).
    blockers = _placed_blockers(placed, buffer_cm=30.0 if room_type == "bedroom" else 5.0)
    # A bedroom wardrobe / dressing-table ends a real gap SHORT of a door swing (never flush against it);
    # the living console keeps its byte-identical behaviour (door handled by the trim below).
    cands = _wall_band_candidates(
        analysis, depth, min_w, use_solid=True, blockers=blockers,
        door_clearance=_BEDROOM_DOOR_CLEAR_CM if room_type == "bedroom" else 0.0,
    )
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
        # A living console on the wall ADJACENT to the TV wall can crowd the TV at their shared corner
        # (each hugs the corner from its own wall - a cramped, clashing pair). Trim the console's run
        # clear of the TV's footprint + a real gap, so it slides along the wall away from the TV (or
        # takes another wall / is skipped) - the same corner-shadow trim we use for door swings.
        tv_placed = _find_placed(placed, "tv_unit")
        if target == "console" and tv_placed is not None:
            tv_it, tv_pr = tv_placed
            obs.append(item_polygon(tv_it.x, tv_it.y, tv_pr.width_cm, tv_pr.depth_cm, tv_it.rotation_deg).buffer(CONSOLE_TV_CLEAR_CM))
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
    # The dining table's footprint: a console that can't tuck behind the primary sofa should still anchor a
    # ZONE by sitting near the dining as a BUFFET/sideboard, rather than marooned on a far wall.
    dining = _find_placed(placed, "dining_table")
    dining_poly = (
        item_polygon(dining[0].x, dining[0].y, dining[1].width_cm, dining[1].depth_cm, dining[0].rotation_deg)
        if dining is not None else None
    )
    storage_walls: set[int] = set()  # a 2nd storage piece should take a DIFFERENT wall
    for it, pr in placed:
        if placement_group(pr.category) == "storage":
            sf = front_vector(it.rotation_deg)
            storage_walls.add(max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, sf)))
    # Walls a DESK backs onto. The work nook outranks the dressing table (user rule): the desk is placed
    # first and OWNS its wall, so a dressing-table candidate on the desk's wall is dropped - if that leaves
    # the vanity no clean wall of its own, it's skipped (the work nook wins the tie / the last wall).
    # When a TV is requested it OWNS the wall the bed faces (opposite the headboard), so it lands centred
    # in front of the bed. A bedroom wardrobe / dresser then SHIFTS to a side wall - reserve that wall by
    # penalising it here (a strong penalty, not a hard skip, so a wardrobe is never left unplaceable).
    bed_faces = None
    bed_for_tv = _find_placed(placed, "bed")
    if room_type == "bedroom" and tv_requested and bed_for_tv is not None:
        bfv = front_vector(bed_for_tv[0].rotation_deg)
        bed_faces = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, (-bfv[0], -bfv[1])))
    # The accent chair is now placed BEFORE the console (recipe: companion_seating -> storage) and has
    # taken one (or both) flank(s) of the seating group. The console must land on a wall AWAY from it,
    # never crowding the chair's side. Living-room console only (keyed on has_tv, like the other console
    # rules) - a majlis has no chair-vs-console balance.
    chair_items = [
        (it, pr) for it, pr in placed if placement_group(pr.category) == "accent_chair"
    ] if (target == "console" and has_tv) else []
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
            # Keep a real GAP off any accent CHAIR: carve the run clear of each chair whose approach
            # falls on this wall (a chair placed IN FRONT of the console violates the chair<->console
            # gap - the 7+ seat case, where an extra chair lands by the console), keeping the LARGER clear
            # stretch so the console SLIDES ALONG the wall to a spot that isn't jammed against a chair.
            # A whole-wall reject would waste the wall's clear far end; carving relocates instead. If no
            # stretch survives, the wall is skipped below.
            lo, hi = cand.lo, cand.hi
            for it, pr in chair_items:
                rel = sub2((it.x, it.y), w.start)
                if not (0.0 < dot(rel, w.normal) < depth + 80.0):
                    continue  # chair not near this wall's approach
                proj = dot(rel, w.dir)
                clr = max(pr.width_cm, pr.depth_cm) / 2.0 + 45.0  # chair half + a real walk-past gap
                aa, bb = proj - clr, proj + clr
                if bb <= lo or aa >= hi:
                    continue
                left, right = (lo, min(hi, aa)), (max(lo, bb), hi)
                lo, hi = left if (left[1] - left[0]) >= (right[1] - right[0]) else right
            if hi - lo < min_w:
                continue  # no stretch of this wall keeps a gap from a chair
            cand = _BandCandidate(wall=w, lo=lo, hi=hi, piece=cand.piece, extent=hi - lo)
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
            # A requested TV OWNS the wall the bed faces - the dresser never takes it. Otherwise the
            # dresser may share the DESK's wall when there's clear room beside the desk (large rooms fit
            # BOTH); the desk's footprint is a blocker + the sit-room / nightstand carves below keep them
            # apart, so a wall with no room left simply yields no candidate here and the vanity is
            # skipped - the work nook wins the tie (bedroom drop priority).
            if bed_faces is not None and w.index == bed_faces:
                continue
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
                continue  # no stretch of this wall clears the nightstand -> SKIP it: a dressing table
                # must NEVER cross / crowd a side table, so it yields (drops) rather than sharing a corner
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
            # Keep a comfortable GAP from a nightstand on an ADJACENT wall - they clash at a shared corner
            # (the generic corner-trim can miss it when the bed's buffer merges the shadow). Carve the run
            # clear of each nearby nightstand's projection + a gap and keep the larger side, so the wardrobe
            # SLIDES along the wall away from the nightstand instead of crowding it. If nothing survives,
            # keep the full run (no skip - the wardrobe is essential) so a tight room still gets one.
            lo, hi = cand.lo, cand.hi
            for it, pr in placed:
                if placement_group(pr.category) != "side_table":
                    continue
                rel = sub2((it.x, it.y), w.start)
                if not (0.0 < dot(rel, w.normal) < depth + 60.0):
                    continue  # nightstand not near this wall's approach
                proj = dot(rel, w.dir)
                clr = max(pr.width_cm, pr.depth_cm) / 2.0 + WARDROBE_SIDE_TABLE_CLEAR_CM
                a, b = proj - clr, proj + clr
                if b <= lo or a >= hi:
                    continue
                left, right = (lo, min(hi, a)), (max(lo, b), hi)
                lo, hi = left if (left[1] - left[0]) >= (right[1] - right[0]) else right
            if hi - lo >= min_w:
                cand = _BandCandidate(wall=w, lo=lo, hi=hi, piece=cand.piece, extent=hi - lo)
        entry_norm = _entry_distance_norm(analysis, cand.piece)  # 1 = far from the entry, 0 = at it
        # In a MASSIVE room (>= 60 m2), a living-room console is an ENTRYWAY console: it PRIORITISES being NEAR
        # the door over sitting on the LONGEST wall - so it tucks by the entry instead of hogging a central
        # wall the chaise needs. Extent weight drops (a wall only has to FIT the console, enforced by min_w),
        # near-entry weight rises. Everywhere else (smaller rooms, bedroom, majlis) keeps the original score,
        # so nothing below the massive threshold changes (goldens are all < 40 m²).
        massive_console = target == "console" and has_tv and analysis.area_cm2 >= MASSIVE_ROOM_MIN_CM2
        if massive_console:
            score = 0.3 * (cand.extent / max_extent) + 0.6 * (1.0 - entry_norm) - pen
        else:
            score = 0.7 * (cand.extent / max_extent) + 0.3 * entry_norm - pen
        if target == "console" and has_tv and behind_usable and w.index == behind_wall:
            score += 0.5  # tuck the console behind a FLOATED primary sofa (only if usable room behind)
        elif target == "console" and dining_poly is not None:
            # Otherwise anchor it to the DINING as a buffet: reward a wall near the dining set, tapering to
            # zero by ~3m away, so a console that can't be a sofa-back piece stands with the dining zone
            # rather than orphaned on a far wall. (Skipped on the behind-primary wall - that bonus wins.)
            score += 0.5 * max(0.0, 1.0 - cand.piece.distance(dining_poly) / 300.0)
        if w.index in storage_walls:
            score -= 0.5  # a wall already carrying storage - prefer a different one (fall back if forced)
        if bed_faces is not None and w.index == bed_faces:
            score -= 0.9  # reserve the bed-facing wall for the TV -> the wardrobe/dresser shift to a side wall
        # BEDROOM storage CENTRES in its clear run: the door swing is already trimmed out of the run
        # (door_clearance in _wall_band_candidates), so centring keeps the piece off the door AND off the
        # wall ENDS - a wardrobe / vanity hugged into a corner reads as "cornered" (user, repeated). The
        # living console keeps its centred placement too (anchor stays None). The DRESSING TABLE is the
        # exception: it centres too, BUT if a centred vanity's stool would be crowded by the bed it slides
        # along the wall the MINIMUM needed to free the stool (`_vanity_clear_anchor`) - so the vanity is
        # "placed where its chair fits" without being cornered (user).
        is_vanity = room_type == "bedroom" and store_category == "dressing-table"
        if is_vanity:
            bed_pl = _find_placed(placed, "bed")
            bed_poly = (
                item_polygon(bed_pl[0].x, bed_pl[0].y, bed_pl[1].width_cm, bed_pl[1].depth_cm, bed_pl[0].rotation_deg)
                if bed_pl is not None else None
            )
            anchor_t = _vanity_clear_anchor(cand, bed_poly)  # None -> centred (stool already clears)
        elif room_type == "bedroom":
            anchor_t = None  # centre the wardrobe in its clear run - never corner it
        else:
            anchor_t = None
        zones.append(_band_zone(analysis, cand, "storage", i, score, [R_REMAINING_WALL], depth, anchor_t=anchor_t))
    return _rank(zones)


def _beside_console_spots(analysis: RoomAnalysis, placed: list[PlacedProduct], size: float = 60.0) -> list[ZoneData]:
    """SECONDARY plant location: tucked at either END of the console, hugging the console's wall. Used
    only when no empty corner survives (scored BELOW the corners) - a plant beside the console beats
    skipping it, PROVIDED it genuinely fits with a clear gap and overlaps nothing. Clipped against
    furniture (the console included), keep-clear zones and door swings, so a spot that doesn't fit is
    dropped rather than crammed."""
    console = _find_placed(placed, "storage")
    if console is None:
        return []
    it, pr = console
    f = front_vector(it.rotation_deg)  # the console faces INTO the room (away from its wall)
    w = width_axis(it.rotation_deg)    # along the console's width (i.e. its wall)
    blockers = _placed_blockers(placed, buffer_cm=8.0)
    door_keepout = unary_union([sw.buffer(30.0) for sw in analysis.swing_arcs.values()]) if analysis.swing_arcs else None
    back = add((it.x, it.y), f, -pr.depth_cm / 2.0)  # midpoint of the console's back edge (at the wall)
    zones: list[ZoneData] = []
    for idx, side in enumerate((-1.0, 1.0)):
        # hug the same wall (back ~2cm off it), offset past the console's end by a real gap
        origin = add(add(back, f, size / 2.0 + 2.0), w, side * (pr.width_cm / 2.0 + size / 2.0 + 12.0))
        rect = item_polygon(origin[0], origin[1], size, size, it.rotation_deg)
        clipped = rect.intersection(analysis.polygon).difference(analysis.keep_clear_union).difference(blockers)
        if door_keepout is not None:
            clipped = clipped.difference(door_keepout)
        piece = largest_piece(clipped)
        if piece is None or piece.area < size * size * 0.9:  # must genuinely fit - no meaningful clip/overlap
            continue
        zones.append(
            _frame_zone(
                "decor", 20 + idx, piece, 0.5, 0.0, origin, (0.0, 1.0), (1.0, 0.0),
                size, size, [R_FLEXIBLE_SPOT], f"beside_console_{idx}", kind="free",
            )
        )
    return zones


def _decor_zones(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    stats: CategoryStats,
    blocker_buffer: float = 30.0,
    size: float = 60.0,
) -> list[ZoneData]:
    sofa = _find_placed(placed, "sofa")
    near = (sofa[0].x, sofa[0].y) if sofa is not None else None
    # Prefer corners near the seating, but consider EVERY corner (radius = room diagonal): in a
    # big room the near corners are often taken by lamps, so a plant should still fill an empty
    # far corner rather than being skipped.
    # Keep the plant a real clearance off other furniture (like the floor lamp) - an 8cm buffer let it
    # sit ~2cm from the service-table in a near-sofa corner. A 30cm buffer shrinks a crowded corner
    # below the fit threshold, so the plant fills a genuinely EMPTY corner instead of crowding a piece.
    # A BEDROOM passes a smaller buffer + a room-scaled `size` (a small decorative pot may tuck
    # close to a wardrobe/chair, and a big bedroom wants a substantial plant); the living room
    # keeps the defaults (30 cm / 60 cm), so its corners are byte-identical to before.
    corners = _corner_spots(
        analysis, placed, "decor", size, max_zones=4,
        near=near, near_radius=analysis.diag_cm if near else 0.0, reasons=[R_FLEXIBLE_SPOT],
        blocker_buffer=blocker_buffer,
    )
    # SECONDARY location: beside the console. Ranked BELOW the corners (0.5 vs 0.7+), so a genuinely
    # empty corner always wins; the plant tucks beside the console only when no corner survives -
    # beating a skipped plant, and only if it fits without overlapping anything.
    beside = _beside_console_spots(analysis, placed, size=60.0)
    return _rank(corners + beside, limit=4)


def _lamp_on_table_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """A table lamp resting ON each nightstand: one small free zone centred on EVERY placed
    side table (up to two), sized to (most of) its top so only a small lamp fits - not a floor
    lamp. Each lamp shares its table's footprint; that overlap is expected and exempted in
    validation. Two nightstands -> a mirrored PAIR of matching bedside lamps."""
    zones: list[ZoneData] = []
    idx = 0
    for item, product in placed:
        if placement_group(product.category) != "side_table":
            continue
        s = min(product.width_cm, product.depth_cm) * 0.8  # fits a small lamp base on the table top
        poly = item_polygon(item.x, item.y, s, s, item.rotation_deg)
        zones.append(
            _frame_zone(
                "lighting", idx, poly, 0.9, item.rotation_deg,
                (item.x, item.y), (0.0, 1.0), (1.0, 0.0), s, s,
                [R_FLEXIBLE_SPOT], "on_nightstand", kind="free",
            )
        )
        idx += 1
    return zones


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
    """The bedroom accent chair: always a READING CHAIR in a clear, door-free corner, angled to face
    the bed. The dressing table gets its OWN stool, not this chair."""
    bed = _find_placed(placed, "bed")
    far = (bed[0].x, bed[0].y) if bed is not None else None
    return _corner_spots(
        analysis, placed, "accent_chair", 70.0, max_zones=3, far_from=far, face=far,
        reasons=[R_FLEXIBLE_SPOT], blocker_buffer=28.0,
    )


def _seat_in_front_of(
    analysis: RoomAnalysis, item: PlacedItem, product: Product, label: str, lat_offset: float = 0.0
) -> list[ZoneData]:
    """A chair pulled up in front of a wall surface you SIT AT (a vanity or a desk): centred on
    the surface and turned to FACE it, ~8 cm off the front so it can pull out. `lat_offset` slides the
    chair along the surface's width (0 = centred) so a vanity stool can sit toward one END of the
    dressing table, clear of the bed, instead of dead-centre. Empty list if there is no room to sit."""
    f = front_vector(item.rotation_deg)  # the surface faces into the room
    w = width_axis(item.rotation_deg)
    origin = add(add((item.x, item.y), f, product.depth_cm / 2.0 + 8.0), w, lat_offset)
    fwd_len = 62.0  # room for the chair + a little pull-out space
    lat_len = max(52.0, product.width_cm * 0.6)  # centred on the surface's width
    chair_rot = (item.rotation_deg + 180.0) % 360.0  # turn the chair to FACE the surface
    rect = quad(
        add(origin, w, -lat_len / 2.0),
        add(origin, w, lat_len / 2.0),
        add(add(origin, w, lat_len / 2.0), f, fwd_len),
        add(add(origin, w, -lat_len / 2.0), f, fwd_len),
    )
    piece = largest_piece(rect.intersection(analysis.polygon).difference(analysis.keep_clear_union))
    if piece is None or piece.area < 2_000.0:
        return []
    return [
        _frame_zone(
            "accent_chair", 0, piece, 0.95, chair_rot, origin, f, w, fwd_len, lat_len,
            [R_FLEXIBLE_SPOT], label,
        )
    ]


_DESK_SIT_CLEAR_CM = 60.0  # clear floor in front of the desk to pull a chair up to it
_DESK_BED_CLEAR_CM = 70.0  # keep the desk this far off the bed so the passage beside it stays walkable
# bedroom wall pieces (desk / wardrobe / dressing-table) end this far SHORT of a door swing (not flush =
# "touching the door"). Larger than the living-room TV clearance - a bedroom door swings into a tighter room.
_BEDROOM_DOOR_CLEAR_CM = 40.0


def _desk_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats, tv_requested: bool = True
) -> list[ZoneData]:
    """The bedroom work-nook DESK (an office table): against a clear SOLID wall with room to SIT at it,
    on a wall AWAY from the bed and the wardrobe / dressing-table (the few clear bedroom walls compete).

    Reuses the wall-band machinery. Keeps a real gap off the DOOR swing (never flush) and a walkable
    PASSAGE off the bed. A wall with no sitting room, a blocked walkway, or already carrying the bed /
    storage is PENALISED (not hard-dropped), so the desk lands on the BEST available wall - or yields
    nothing (skipped) when no wall genuinely holds it. Bedroom-only (no living recipe uses `desk`).
    """
    s = stats.get("desk", {})
    depth = s.get("max_d", 70.0) + 6.0
    min_w = min(s.get("min_w", 90.0), 90.0)
    blockers = _placed_blockers(placed, buffer_cm=30.0)  # keep a real margin off other pieces
    # Keep a WALKABLE PASSAGE off the bed: buffer the bed extra so the desk never crowds it (a desk
    # jammed beside the bed blocks the way past). Excludes the band, so the desk simply takes a wall
    # far enough from the bed - or, in a tight room, yields (skipped) rather than squeezing the passage.
    bed = _find_placed(placed, "bed")
    if bed is not None:
        bed_clear = item_polygon(
            bed[0].x, bed[0].y, bed[1].width_cm, bed[1].depth_cm, bed[0].rotation_deg
        ).buffer(_DESK_BED_CLEAR_CM)
        blockers = unary_union([blockers, bed_clear]) if (blockers is not None and not blockers.is_empty) else bed_clear
    # door_clearance ends the band a real gap SHORT of any door swing (not flush = "touching the door").
    cands = _wall_band_candidates(
        analysis, depth, min_w, use_solid=True, blockers=blockers, door_clearance=_BEDROOM_DOOR_CLEAR_CM
    )
    if not cands:
        return []
    # Trim a candidate's run clear of adjacent-wall furniture (the door swing is handled by door_clearance).
    obs = [blockers] if (blockers is not None and not blockers.is_empty) else []
    if obs:
        cands = _trim_band_extent(cands, analysis, depth, unary_union(obs), min_w)
    if not cands:
        return []
    # The desk belongs on a SIDE wall - never on the bed's headboard wall nor the wall it faces (the TV
    # wall). Those are HARD-excluded (`block_hard`): if the only room left is there, the desk drops rather
    # than sit behind the bed or on the TV wall. Softer preferences:
    #  - `sofa_walls` (STRONG penalty): the lounge sofa is placed FIRST now and owns a toe-side wall; the
    #    desk takes the OTHER side (the user's swap). It only shares the sofa's wall as a last resort (a
    #    room with a single usable side wall), which reads better than dropping the desk.
    #  - `storage_walls` (MILD): prefer a private wall, but share the wardrobe/vanity side over the sofa's.
    block_hard: set[int] = set()
    sofa_walls: set[int] = set()
    storage_walls: set[int] = set()
    if bed is not None:
        bf = front_vector(bed[0].rotation_deg)
        block_hard.add(max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, bf)))
        if tv_requested:
            block_hard.add(max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, (-bf[0], -bf[1]))))
    for it, pr in placed:
        g = placement_group(pr.category)
        if g == "storage":
            sf = front_vector(it.rotation_deg)
            storage_walls.add(max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, sf)))
        elif g == "sofa":
            sf = front_vector(it.rotation_deg)
            sofa_walls.add(max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, sf)))
    furniture_polys = [
        item_polygon(it.x, it.y, pr.width_cm, pr.depth_cm, it.rotation_deg)
        for it, pr in placed if not pr.is_walkable
    ]
    max_extent = max(c.extent for c in cands)
    zones: list[ZoneData] = []
    for i, cand in enumerate(cands):
        w = cand.wall
        if w.index in block_hard:
            continue  # never the headboard / TV wall - the desk belongs on a side wall (or drops)
        pen = 0.0
        # room to SIT: the band extended a chair-depth forward must be clear of standing furniture.
        approach = quad(
            add(w.point_at(cand.lo), w.normal, 2.0), add(w.point_at(cand.hi), w.normal, 2.0),
            add(w.point_at(cand.hi), w.normal, 2.0 + depth + _DESK_SIT_CLEAR_CM),
            add(w.point_at(cand.lo), w.normal, 2.0 + depth + _DESK_SIT_CLEAR_CM),
        )
        if any(approach.intersection(fp).area > 6_000.0 for fp in furniture_polys):
            pen += 0.5  # no room to pull a chair up here - a last resort, not a skip
        if _corridor_overlap_ratio(analysis, cand.piece) > 0.05:
            pen += 0.4
        if w.index in sofa_walls:
            pen += 1.0  # take the side OPPOSITE the lounge sofa (the swap); share it only if forced
        elif w.index in storage_walls:
            pen += 0.4  # prefer a private wall, but share the wardrobe/vanity side over the sofa's
        entry_norm = _entry_distance_norm(analysis, cand.piece)
        score = 0.7 * (cand.extent / max_extent) + 0.3 * entry_norm - pen
        # If the desk's wall meets the door at one end, slide the desk DOWN the wall to the far end,
        # clear of the entry (so it never sits right beside the door - the shared-wall wardrobe already
        # slid down too, leaving the desk this near-door-clear stretch).
        anchor_t = _door_far_anchor(analysis, cand)
        zones.append(_band_zone(analysis, cand, "desk", i, score, [R_REMAINING_WALL], depth, anchor_t=anchor_t))
    return _rank(zones)


def _desk_chair_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """The work-nook CHAIR: pulled up in front of the placed desk, facing it - the same mechanism as
    the vanity seat. No desk placed -> no chair (never orphaned)."""
    desk = _find_placed(placed, "desk")
    if desk is None:
        return []
    return _seat_in_front_of(analysis, desk[0], desk[1], "at_desk")


_VANITY_BED_CLEAR_CM = 45.0  # a vanity stool keeps this walkable gap off the bed


def _vanity_chair_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """The dressing-table's STOOL: a small chair pulled up in front of the vanity, facing it (reuses
    `_seat_in_front_of`). Placed ONLY where it won't block a walkway or crowd the bed - the seat area
    must clear any corridor AND keep a real gap off the bed; otherwise the stool is DROPPED (the vanity
    keeps its wall, just chair-less) rather than jutting into the passage or against the bed. No dressing
    table placed -> no stool (never orphaned).

    The vanity stays CENTRED on its wall (never cornered); so when the CENTRED stool would crowd the bed
    (the vanity's wall meets the bed at a corner), the STOOL - not the vanity - slides toward the table end
    FARTHER from the bed: a chair BESIDE the vanity, still usable and under the vanity's own width. The
    centred spot is tried first, so a vanity with clear room in front is byte-identical to before."""
    vanity = next(((it, p) for it, p in placed if p.category == "dressing-table"), None)
    if vanity is None:
        return []
    v_it, v_pr = vanity
    bed = _find_placed(placed, "bed")
    bed_poly = (
        item_polygon(bed[0].x, bed[0].y, bed[1].width_cm, bed[1].depth_cm, bed[0].rotation_deg)
        if bed is not None else None
    )

    def ok(z: ZoneData) -> bool:
        if _corridor_overlap_ratio(analysis, z.polygon) > 0.10:
            return False  # the stool would sit in a walkway/passage
        if bed_poly is not None and z.polygon.distance(bed_poly) < _VANITY_BED_CLEAR_CM:
            return False  # too close to the bed
        return True

    # Lateral offsets to try: centred first, then progressively slid toward the table end FARTHER from the
    # bed (finest step first, so the stool moves the MINIMUM needed to clear). Capped near the vanity's own
    # half-width so the stool sits at most at the table's END - a chair BESIDE the vanity, never marooned.
    # Only the SOLE vanity (no wardrobe) slides off-centre. With a wardrobe the vanity is already slid off
    # the bed by `_vanity_clear_anchor` (payload 5) and the stool stays centred-only, because the extra
    # off-centre stool placement perturbs which bed-pinned template wins and drops the 2nd-storage vanity.
    has_wardrobe = any(p.category == "wardrobe" for _it, p in placed)
    offsets = [0.0]
    if bed_poly is not None and not has_wardrobe:
        w = width_axis(v_it.rotation_deg)
        bc = bed_poly.centroid
        bed_side = dot(sub2((bc.x, bc.y), (v_it.x, v_it.y)), w)  # >0: bed toward +w along the vanity
        far_sign = -1.0 if bed_side > 0 else 1.0
        max_shift = max(0.0, v_pr.width_cm / 2.0 - 8.0)  # up to the vanity's end (small margin)
        offsets += [far_sign * max_shift * frac for frac in (0.35, 0.55, 0.75, 1.0) if max_shift * frac > 4.0]

    for off in offsets:
        good = [z for z in _seat_in_front_of(analysis, v_it, v_pr, "at_vanity", lat_offset=off) if ok(z)]
        if good:
            return good  # first offset (centred, then increasingly bed-far) that clears the passage + bed
    return []


# The bedroom lounge sofa starts a hair AFTER the bed's foot, so its sitting area reads as clearly
# beyond the bed, not creeping alongside it.
_LOUNGE_BED_END_GAP_CM = 10.0


def _lounge_sofa_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """The bedroom LOUNGE sofa: a compact sofa (the selector best-fits it from sofa / 2-/3-seater)
    hugging a SIDE wall, facing into the room - the seat of a small sitting area, with a centre table
    pulled up in front of it. Placed LAST (after the bed, wardrobe, desk, dresser, TV).

    HARD rules (user): the sofa goes ONLY on a wall that is NEITHER the bed's headboard wall NOR the wall
    the bed FACES (the TV wall) - i.e. a side wall - AND it must START where the bed ENDS (its near edge
    sits just past the bed's foot, extending toward the far/TV wall), so the sitting area is a distinct
    zone beyond the bed, never creeping alongside it. If no side wall has a clear run past the bed's foot,
    NOTHING is returned -> the sofa (and, since it depends on the sofa, the centre table) is dropped.
    Reuses the wall-band machinery; keeps the bedroom door clearance off any swing."""
    bed = _find_placed(placed, "bed")
    if bed is None:
        return []  # no bed -> no anchor for "start where the bed ends" -> no lounge
    s = stats.get("sofa", {})
    depth = s.get("max_d", 95.0) + 8.0
    min_w = min(s.get("min_w", 150.0), 150.0)
    blockers = _placed_blockers(placed, buffer_cm=30.0)
    cands = _wall_band_candidates(
        analysis, depth, min_w, use_solid=True, blockers=blockers, door_clearance=_BEDROOM_DOOR_CLEAR_CM
    )
    if not cands:
        return []
    obs = [blockers] if (blockers is not None and not blockers.is_empty) else []
    if obs:
        cands = _trim_band_extent(cands, analysis, depth, unary_union(obs), min_w)
    if not cands:
        return []
    # The two FORBIDDEN walls: the bed's headboard wall and the wall the bed faces (the TV wall). The
    # sofa may only take one of the remaining SIDE walls.
    bf = front_vector(bed[0].rotation_deg)
    headboard_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, bf))
    tv_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, (-bf[0], -bf[1])))
    forbidden = {headboard_wall, tv_wall}
    # Walls already carrying storage / a desk: the lounge PREFERS a fully clear side wall, but shares a
    # storage wall's leftover if that's all that's left (soft penalty).
    taken_walls: set[int] = set()
    for it, pr in placed:
        if placement_group(pr.category) in ("storage", "desk"):
            sf = front_vector(it.rotation_deg)
            taken_walls.add(max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, sf)))
    foot = add((bed[0].x, bed[0].y), bf, bed[1].depth_cm / 2.0)  # centre of the bed's foot edge
    scored: list[tuple[float, float, _BandCandidate, float]] = []
    for cand in cands:
        w = cand.wall
        if w.index in forbidden:
            continue  # side walls only
        # Trim the run to the part PAST the bed's foot (toward the far/TV wall), then anchor the sofa's
        # near edge there. `foot_t` is the foot's projection onto this wall's axis; the far side of it
        # (in the bed's front direction) is the region beyond the bed. `foot_edge` is where the sofa's
        # near edge WANTS to sit - flush with the toe.
        foot_t = dot(sub2(foot, w.start), w.dir)
        if dot(w.dir, bf) >= 0.0:
            foot_edge = foot_t + _LOUNGE_BED_END_GAP_CM
            lo2, hi2 = max(cand.lo, foot_edge), cand.hi
            anchor_t = lo2
        else:
            foot_edge = foot_t - _LOUNGE_BED_END_GAP_CM
            lo2, hi2 = cand.lo, min(cand.hi, foot_edge)
            anchor_t = hi2
        if hi2 - lo2 < min_w:
            continue  # no clear run past the bed's foot on this wall
        # How far the sofa's near edge ends up from the bed's TOE: 0 when the clear run reaches the foot
        # (the sofa sits right by the toe); large when near-foot furniture pushes it toward the corner.
        toe_gap = abs(anchor_t - foot_edge)
        trimmed = _BandCandidate(wall=w, lo=lo2, hi=hi2, piece=cand.piece, extent=hi2 - lo2)
        pen = 0.4 if _corridor_overlap_ratio(analysis, trimmed.piece) > 0.05 else 0.0
        on_taken = w.index in taken_walls  # a wall already carrying the wardrobe / desk
        scored.append((toe_gap, pen, on_taken, trimmed, anchor_t))
    if not scored:
        return []  # no side wall holds a sofa past the bed's foot -> drop the lounge (sofa + table)
    # HARD-prefer a side wall of the sofa's OWN (not shared with the wardrobe/desk): a sofa + wardrobe on
    # one wall is cramped, and sharing lets a freed-up toe-side wall lure the sofa off the storage wall
    # (flipping which side the desk then takes). Fall back to a shared wall only if no clear one holds it.
    clear = [t for t in scored if not t[2]]
    pool = clear if clear else scored
    max_extent = max(c.extent for _tg, _pen, _ot, c, _at in pool)
    zones: list[ZoneData] = []
    for i, (toe_gap, pen, _ot, cand, anchor_t) in enumerate(pool):
        # NEAR the TOE of the bed wins (user rule): proximity to the foot dominates the score, with a
        # small tie-break for a roomier run so a bigger sofa fits when two walls are both by the toe.
        score = -0.004 * toe_gap - pen + 0.1 * (cand.extent / max_extent)
        zones.append(_band_zone(analysis, cand, "sofa", i, score, [R_REMAINING_WALL], depth, anchor_t=anchor_t))
    return _rank(zones)


def _lounge_light_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """A floor lamp (floor-stand) BESIDE the lounge sofa - tucked at one ARM end, preferring the end
    toward the room corner (away from the bed), just off the sofa's side, completing the sitting-area
    vignette. Tries a couple of forward offsets; the first spot fully inside the room and clear of every
    placed piece (sofa / centre table / walls) wins. No lounge sofa placed -> [] (never orphaned)."""
    sofa = _find_placed(placed, "sofa")
    if sofa is None:
        return []
    item, product = sofa
    w = width_axis(item.rotation_deg)
    f = front_vector(item.rotation_deg)
    s = stats.get("lighting", {})
    sw = min(s.get("max_w", 45.0), 50.0)
    sd = min(s.get("max_d", 45.0), 50.0)
    blockers = _placed_blockers(placed, buffer_cm=5.0)
    inner = analysis.polygon.buffer(-6.0)
    # Keep the lamp OUT of any door swing (+ a 30cm keep-out): tucked off the sofa's foot it can otherwise
    # land right in the door's path when the lounge sofa sits by the door corner.
    swing = unary_union(list(analysis.swing_arcs.values())).buffer(30.0) if analysis.swing_arcs else None
    # And out of any WINDOW strip - a ~150cm floor lamp in front of the glass blocks the light (BLOCKS_WINDOW).
    win = unary_union([strip for strip, _sill in analysis.window_strips.values()]) if analysis.window_strips else None
    bed = _find_placed(placed, "bed")
    bed_pt = (bed[0].x, bed[0].y) if bed is not None else (analysis.polygon.centroid.x, analysis.polygon.centroid.y)

    def _end_pt(sign: float) -> Vec:
        return (item.x + w[0] * sign * product.width_cm / 2.0, item.y + w[1] * sign * product.width_cm / 2.0)

    # Prefer the sofa END farther from the bed (the room-corner end, where a reading lamp reads best).
    ends = sorted((1.0, -1.0), key=lambda sign: dist(_end_pt(sign), bed_pt), reverse=True)
    for sign in ends:
        for fwd in (0.0, 25.0, -20.0, 45.0):
            # sit the lamp a real gap PAST the sofa's arm - the offset must clear the 5cm blocker buffer
            # (else the lamp's edge just touches the sofa's shadow and every spot is rejected).
            off = product.width_cm / 2.0 + sw / 2.0 + 12.0
            cx = item.x + w[0] * sign * off + f[0] * fwd
            cy = item.y + w[1] * sign * off + f[1] * fwd
            poly = item_polygon(cx, cy, sw, sd, item.rotation_deg)
            if (inner.contains(poly) and (blockers.is_empty or not poly.intersects(blockers))
                    and (swing is None or not poly.intersects(swing))
                    and (win is None or not poly.intersects(win))):
                return [_frame_zone("lighting", 0, poly, 0.7, item.rotation_deg, (cx, cy), f, w, sd, sw, [R_FLEXIBLE_SPOT], "lounge_side", kind="free")]
    return []


# Circulation walkway the chaise-lounge must keep clear of every placed piece (it's a lounge spot you
# walk to/around) - larger than the plain no-overlap margin. No wall run affords it -> the chaise skips.
_CHAISE_CIRCULATION_CM = 60.0
_CHAISE_FRONT_PASSAGE_CM = 70.0  # a chaise slides along its wall to keep this walk-past clear of a sofa floating in front


def _chaise_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """A STANDALONE chaise-lounge placed as a WALL-HUGGING lounge piece: its back against a clear
    wall, long side PARALLEL to that wall, oriented to FACE INTO the room - exactly the way the
    sofa / console / TV hug a wall (not a corner diagonal). It reuses the shared wall-band
    infrastructure (`_wall_band_candidates` + `_band_zone`), so the pose and orientation come from
    the wall itself (`rotation_for_normal`, front vector pointing off the wall into the room).

    It seeks a genuinely CLEAR secondary wall BESIDE or ACROSS FROM the seating - never behind it:
    it hard-excludes every wall a seating piece BACKS ONTO (the primary sofa AND the L-return, and a
    floated sofa's back wall), so it never sits behind the group; plus the TV wall and any wall whose
    clear run overlaps a walkway;
    it PREFERS a wall away from the door (a soft penalty, not a hard drop); it keeps a 20cm gap off
    every placed piece (the seating group / coffee table) and the standard 30cm keep-out off door
    swings, and trims a candidate's run where a swing or adjacent furniture clips its corner. No
    clean wall survives -> [] -> the caller skips the chaise (a 'didn't fit' notice)."""
    s = stats.get("chaise", {})
    depth = s.get("max_d", 80.0) + 8.0
    min_w = min(s.get("min_w", 140.0), 140.0)
    # Keep a real CIRCULATION gap around the chaise, not just a no-overlap margin: it must sit a walkway
    # off every placed piece (sofa / L-return / coffee table / the accent chairs, which are placed
    # BEFORE it now), so you can actually walk to and around it. If no wall run clears that, the chaise
    # is skipped ('didn't fit') rather than jammed against a chair. The walkable rug is excluded, so the
    # chaise may still kiss the rug's edge.
    blockers = _placed_blockers(placed, buffer_cm=_CHAISE_CIRCULATION_CM)
    # Hug a SOLID wall stretch (like the console / TV), holding the standard 30cm clear of any swing.
    cands = _wall_band_candidates(analysis, depth, min_w, use_solid=True, blockers=blockers, door_clearance=30.0)
    if not cands:
        return []

    # Trim a candidate's run where a door swing OR adjacent-wall furniture clips its corner, so a
    # chaise centred on it can't poke into the door or the neighbouring piece.
    obs = [blockers] if (blockers is not None and not blockers.is_empty) else []
    obs += [sw.buffer(30.0) for sw in analysis.swing_arcs.values()]
    if obs:
        cands = _trim_band_extent(cands, analysis, depth, unary_union(obs), min_w)
    if not cands:
        return []


    # Walls to avoid: every wall BEHIND the seating group (never crammed beside/behind the main
    # seating), the TV wall, and - preferably - the door wall.
    door_walls = {d.wall_index for d in analysis.room.doors}
    tv = _find_placed(placed, "tv_unit")
    tv_wall = None
    if tv is not None:
        # COMPLETELY exclude the TV wall - the chaise never shares it, even when the TV leaves a clear
        # stretch beside it. A chaise on the media wall reads as "sitting on the TV table"; the media zone
        # stays the TV's alone. The chaise belongs on another clear wall (ideally the console's - see the
        # console-wall bonus below); if none survives it is dropped with a notice, never crammed by the TV.
        tv_f = front_vector(tv[0].rotation_deg)
        tv_wall = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, tv_f))
    # The walls BEHIND the seating group: for EVERY placed seating piece (primary sofa AND the
    # L-return - an L-group backs onto two walls), the wall it backs onto is the one whose inward
    # normal best aligns with the piece's FRONT vector (equivalently, the wall its back edge faces).
    # Exclude that wall whether the piece HUGS it (primary / a corner L-return) or FLOATS off it (a
    # great-room sofa or a floated L-return) - a chaise on any of these walls sits BEHIND the group.
    # A wall counts as "behind the seating" (chaise-excluded) in two cases:
    #  - the PRIMARY sofa's back wall - genuinely behind the conversation group (whether the primary hugs
    #    it or floats off it in a great room);
    #  - a RETURN sofa's back wall ONLY when that return actually HUGS the wall (its back edge is near it),
    #    e.g. an L-return tucked against a side wall.
    # A U-arm floating in the CENTRE merely FACES a far side wall - it does NOT sit against it - so that
    # open wall stays available for the chaise (the old code excluded it purely on orientation, which
    # dropped the chaise in a centred U where every wall got wrongly marked).
    sofa_list = [(it, pr) for it, pr in placed if placement_group(pr.category) == "sofa"]
    primary_sofa = max(sofa_list, key=lambda ip: ip[1].width_cm) if sofa_list else None
    seating_back_walls: set[int] = set()
    # Ranges DIRECTLY behind a seating piece on its back wall: (wall_index, lo, hi) along the wall. A
    # chaise whose run overlaps one sits behind the group; a run PAST it (further along the same wall) is
    # BESIDE the group and stays allowed. This is the precise version of "behind the seating" - a whole
    # 9m wall isn't off-limits just because a floated sofa occupies one 2m stretch of it.
    seating_shadows: list[tuple[int, float, float]] = []

    def _add_shadow(wi: int) -> None:
        sp = item_polygon(it.x, it.y, pr.width_cm, pr.depth_cm, it.rotation_deg)
        slo, shi = extent_along(sp, analysis.walls[wi].start, analysis.walls[wi].dir)
        seating_shadows.append((wi, slo - _CHAISE_CIRCULATION_CM, shi + _CHAISE_CIRCULATION_CM))

    for it, pr in sofa_list:
        sf = front_vector(it.rotation_deg)
        back = max(range(len(analysis.walls)), key=lambda i: dot(analysis.walls[i].normal, sf))
        if primary_sofa is not None and it is primary_sofa[0]:
            # The primary's back wall is behind the conversation group - but only DIRECTLY behind the sofa.
            # On a long wall a FLOATED primary occupies just one stretch; the wall PAST its span (e.g. below
            # a floated primary, beside the console it shares that wall with) is beside the group, not behind
            # it, so the chaise may hug it there. Exclude the sofa's along-wall shadow, not the whole wall.
            _add_shadow(back)
            continue
        back_gap = dot(sub2((it.x, it.y), analysis.walls[back].start), analysis.walls[back].normal) - pr.depth_cm / 2.0
        if back_gap >= 60.0:
            # A floated U-arm merely FACING a far wall leaves the wall available - EXCEPT the stretch
            # DIRECTLY behind it: a chaise hugging the wall right behind a floated sofa can't clear it
            # (the sofa's back sits < a chaise-depth off the wall) and settles into a graze. Shadow the
            # sofa's along-wall span so the chaise takes the CLEAR stretch beside it, not the spot behind.
            _add_shadow(back)
            continue
        # A RETURN that HUGS this wall: exclude the wall ONLY if the return leaves no CLEAR stretch long
        # enough for the chaise beside it (else the chaise takes the clear part, kept off the return by the
        # circulation blockers - not "behind" it). Wall length minus the return's along-wall span.
        wlen = analysis.walls[back].length if hasattr(analysis.walls[back], "length") else dist(analysis.walls[back].start, analysis.walls[back].end)
        if wlen - pr.width_cm < min_w + 2.0 * _CHAISE_CIRCULATION_CM:
            seating_back_walls.add(back)
        else:
            _add_shadow(back)  # long wall: keep only the stretch past the return off-limits, not all of it

    # The chaise is a SEPARATE lounge spot - it should sit AWAY from the conversation seating, not crammed
    # beside it. Reward a candidate by how far its centre is from the seating group's centroid.
    seating_centroid = None
    if sofa_list:
        su = unary_union([item_polygon(it.x, it.y, pr.width_cm, pr.depth_cm, it.rotation_deg) for it, pr in sofa_list])
        seating_centroid = (su.centroid.x, su.centroid.y)

    max_extent = max(c.extent for c in cands)
    zones: list[ZoneData] = []
    for i, cand in enumerate(cands):
        w = cand.wall
        if w.index in seating_back_walls or (tv_wall is not None and w.index == tv_wall):
            continue  # hard-exclude a hugging-seating wall and the TV wall outright
        # Trim the run to the part CLEAR of every behind-seating shadow on this wall: a FLOATED sofa
        # blocks only its own along-wall span, so the stretch PAST it (below a floated primary, beside its
        # console) stays usable. Keep the largest clear sub-run; if none reaches a chaise width the wall is
        # genuinely all behind the seating -> skip.
        shadows = [(slo, shi) for wi, slo, shi in seating_shadows if wi == w.index]
        # Also block the door WALK-IN corridor's footprint along this wall: a door on this same wall
        # sweeps its path across one end, but the stretch clear of it (e.g. below the console, above the
        # door path) is still a good lounge spot - so trim to it rather than dropping the whole wall.
        for cor in analysis.corridors:
            inter = cor.polygon.intersection(cand.piece)
            if getattr(inter, "area", 0.0) > 1.0:
                for g in (inter.geoms if inter.geom_type.startswith("Multi") else [inter]):
                    try:
                        shadows.append(extent_along(g, w.start, w.dir))
                    except Exception:
                        pass
        clear = _largest_clear_interval(cand.lo, cand.hi, shadows)
        if clear is None or clear[1] - clear[0] < min_w:
            continue
        if clear != (cand.lo, cand.hi):
            # Rebuild the footprint from the trimmed run so the walkway check (and the zone polygon) reflect
            # the stretch PAST the sofa's shadow, not the full over-reported wall (which would still overlap
            # the door corridor at the far end and wrongly drop this candidate).
            lo, hi = clear
            band = quad(add(w.point_at(lo), w.normal, 2.0), add(w.point_at(hi), w.normal, 2.0),
                        add(w.point_at(hi), w.normal, 2.0 + depth), add(w.point_at(lo), w.normal, 2.0 + depth))
            piece = band.intersection(analysis.polygon).difference(analysis.keep_clear_union)
            if piece.is_empty:
                continue
            if piece.geom_type == "MultiPolygon":
                piece = max(piece.geoms, key=lambda g: g.area)
            cand = _BandCandidate(wall=w, lo=lo, hi=hi, piece=piece, extent=hi - lo)
        if _corridor_overlap_ratio(analysis, cand.piece) > 0.05:
            continue  # a walkway-blocking run
        # STRICT circulation gate - the chaise is placed ONLY where it GENUINELY fits, never forced. Its
        # actual footprint must keep a real walkway (_CHAISE_CIRCULATION_CM) from every INTERIOR piece -
        # the dining set, floated seating, anything NOT hugging this same wall. (It may sit close to a WALL
        # NEIGHBOUR on its own wall, e.g. the console it pairs with - those don't need a walk-between.) The
        # wall-band carving under-counts a piece whose buffer only nicks the band's inner corner (dining
        # chairs just beyond the band), so this footprint check is the real gate. If it can't clear the
        # interior furniture, this wall doesn't fit - skip it; if no wall fits, the chaise drops honestly.
        anchor_t = _chaise_clear_offset(analysis, cand, sofa_list, depth, min_w)
        mid_t = anchor_t if anchor_t is not None else (cand.lo + cand.hi) / 2.0
        if cand.hi - cand.lo > min_w + 4.0:
            mid_t = min(max(mid_t, cand.lo + min_w / 2.0 + 2.0), cand.hi - min_w / 2.0 - 2.0)
        c_center = add(w.point_at(mid_t), w.normal, depth / 2.0 + 4.0)
        c_foot = item_polygon(c_center[0], c_center[1], min_w, depth, rotation_for_normal(w.normal))
        # The pieces the chaise must keep a WALKWAY from: NON-seating interior furniture (the dining set,
        # a console/side-table on another wall). The conversation SEATING (sofas + the flanking chairs) is
        # what the chaise BELONGS beside, so it is exempt - it may sit right by the group (the wall-band
        # already keeps it off their footprints). A DINING chair (near the dining table) is NOT flanking.
        dining_tbl = _find_placed(placed, "dining_table")
        dt_poly = (item_polygon(dining_tbl[0].x, dining_tbl[0].y, dining_tbl[1].width_cm, dining_tbl[1].depth_cm, dining_tbl[0].rotation_deg)
                   if dining_tbl is not None else None)
        interior = []
        for it2, pr2 in placed:
            if pr2.is_walkable or placement_group(pr2.category) == "sofa":
                continue
            p2 = item_polygon(it2.x, it2.y, pr2.width_cm, pr2.depth_cm, it2.rotation_deg)
            if pr2.category in ("accent_chair", "chair") and (dt_poly is None or p2.distance(dt_poly) > 90.0):
                continue  # a flanking conversation chair, part of the group the chaise belongs beside
            interior.append(p2)  # every other non-seating piece (console, dining, side table, ...) needs a gap
        # The chaise keeps a real walkway from every such piece - INCLUDING a console on its own wall: it may
        # NOT stack tight against it (touching/1cm) NOR float directly in front of it. If a wall's only spot
        # can't clear the console by this gap, the chaise takes another wall or drops (never crammed by it).
        if interior and c_foot.intersects(unary_union([p.buffer(_CHAISE_CIRCULATION_CM) for p in interior])):
            continue
        entry_norm = _entry_distance_norm(analysis, cand.piece)
        # Prefer a clean secondary wall over the door wall - but only PENALISE the door wall when the
        # chaise would actually sit NEAR the door. A door at the FAR end of a long wall (e.g. a 9m wall
        # with the door in the bottom corner) must not exile a chaise placed metres away at the other
        # end: that stretch is a perfectly good lounge spot, often the wall the console already sits on.
        # Full penalty right at the entry, tapering to zero by ~half a room-diagonal clear of it.
        pen = 0.35 * max(0.0, 1.0 - 2.0 * entry_norm) if w.index in door_walls else 0.0
        win_ratio = _window_overlap_ratio(w, cand.lo, cand.hi)
        # The chaise is a SEPARATE lounge spot placed AWAY from the conversation seating (and, per the gate
        # above, a real gap off the console) - reward a candidate by how far its centre sits from the
        # seating group's centroid. (An earlier console-pairing bonus was dropped: the circulation gate now
        # keeps the chaise clear of the console, so a "stack beside the console" pairing can't happen.)
        away_from_seating = 0.0
        if seating_centroid is not None:
            cc = cand.piece.centroid
            away_from_seating = min(1.0, dist((cc.x, cc.y), seating_centroid) / max(analysis.diag_cm * 0.5, 1.0))
        score = (
            0.6 * (cand.extent / max_extent)
            + 0.4 * entry_norm
            - 0.1 * win_ratio
            - pen
            + 0.6 * away_from_seating
        )
        # anchor_t (computed above for the circulation gate) slides the chaise along the wall to the clear
        # stretch, away from a sofa floating in front of it. Only a POSITION hint - the wall is already kept.
        zones.append(_band_zone(analysis, cand, "chaise", i, score, [R_FLEXIBLE_SPOT], depth, anchor_t=anchor_t))
    return _rank(zones)


def _largest_clear_interval(lo: float, hi: float, blocked: list[tuple[float, float]]) -> tuple[float, float] | None:
    """The longest sub-interval of [lo, hi] not covered by any `blocked` (lo, hi) interval. Returns None
    only when [lo, hi] is empty. Used to keep the chaise on the stretch of a wall PAST the along-wall
    shadow of a floated sofa, instead of dropping the whole wall when the run merely clips the shadow."""
    if hi <= lo:
        return None
    clipped = sorted((max(lo, b0), min(hi, b1)) for b0, b1 in blocked if b1 > lo and b0 < hi)
    best = None
    cursor = lo
    for b0, b1 in clipped:
        if b0 - cursor > (best[1] - best[0] if best else 0.0):
            best = (cursor, b0)
        cursor = max(cursor, b1)
    if hi - cursor > (best[1] - best[0] if best else 0.0):
        best = (cursor, hi)
    return best


def _chaise_clear_offset(analysis, cand, sofa_list, depth, min_w) -> float | None:
    """Along-wall position for the chaise that avoids a sofa floating IN FRONT of its wall - the midpoint
    of the larger clear stretch once the in-front sofa's shadow (+ a walk-past) is removed. Returns None
    (centre the run) when no sofa crowds the front, or when no clear stretch of at least a chaise width
    survives. This only PICKS a position; whether the chaise actually places is decided by the strict
    circulation gate in `_chaise_zones` (which drops it if that position can't clear the interior furniture) -
    the chaise is never forced into a too-tight spot."""
    w = cand.wall
    lo, hi = cand.lo, cand.hi
    reach = depth + _CHAISE_FRONT_PASSAGE_CM
    for it, pr in sofa_list:
        sp = item_polygon(it.x, it.y, pr.width_cm, pr.depth_cm, it.rotation_deg)
        try:
            near_edge, far_edge = extent_along(sp, w.start, w.normal)  # distance range OFF the wall
            s_lo, s_hi = extent_along(sp, w.start, w.dir)  # span ALONG the wall
        except Exception:
            continue
        if far_edge <= 0.0 or near_edge >= reach:
            continue  # sofa not floating close in front of this wall
        aa, bb = s_lo - _CHAISE_FRONT_PASSAGE_CM, s_hi + _CHAISE_FRONT_PASSAGE_CM
        if bb <= lo or aa >= hi:
            continue
        left, right = (lo, min(hi, aa)), (max(lo, bb), hi)
        lo, hi = left if (left[1] - left[0]) >= (right[1] - right[0]) else right
    if (hi - lo) >= min_w and (lo, hi) != (cand.lo, cand.hi):
        return (lo + hi) / 2.0
    return None


# The dining chair ring sits ~a chair (≈68 cm) off the table edge; the table pocket is tested against
# the seating buffered by this much LESS the 25 cm already on the seating blockers, so the whole dining
# group (table + ring) clears the conversation group, not just the table.
_DINING_RING_CLEAR_CM = 45.0
_DINING_GROUP_WALKWAY_CM = 90.0  # shifted case: keep the dining table this far off the conversation group
#                                  (so the group-side dining chairs leave a real walk-past, not crammed vs the sofa)
_DINING_WALL_MIN_CM = 40.0  # the table + its chair ring must clear the walls this far, so chairs fit on each side (not crammed into a corner)


def _dining_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """An open rectangular pocket for a dining TABLE, BESIDE the conversation group and never
    overlapping it. We scan the clear floor for a table-sized rectangle that (a) lies entirely
    inside the CLEAR area — the room minus door swings / entry clearances / corridors — so it
    can never block a door or a walkway, and (b) is DISJOINT from every placed item's buffered
    footprint, so it never touches the sofa / L-return / rug / coffee table. The pocket FARTHEST
    from the seating centroid wins (a genuinely separate area — the opposite end or a far
    corner). No clean pocket survives -> [] -> the dining set is skipped ('didn't fit')."""
    s = stats.get("dining_table", {})
    # Target footprint from the catalog, capped so a giant banquet table doesn't demand an
    # impossible pocket; the selector fits a real table to the zone it produces.
    tw = max(90.0, min(s.get("max_w", 150.0), 200.0))
    td = max(70.0, min(s.get("max_d", 90.0), 120.0))

    # The genuinely clear floor: room minus keep-clear (door swings + entry clearances) minus
    # corridors (walkways). Placed items are handled separately (a disjoint test) so the pocket
    # keeps a real gap off the seating group, not merely a non-overlap.
    clear = analysis.polygon.difference(analysis.keep_clear_union)
    if analysis.corridors:
        clear = clear.difference(unary_union([c.polygon for c in analysis.corridors]))
    if clear.is_empty:
        return []
    # Avoid EVERY placed item (buffered 25cm), including the walkable rug — the dining set must
    # keep a real gap off the whole conversation group (sofa / L-return / rug / coffee table).
    placed_polys = [
        item_polygon(i.x, i.y, p.width_cm, p.depth_cm, i.rotation_deg).buffer(25.0)
        for i, p in placed
    ]
    blockers = unary_union(placed_polys) if placed_polys else Polygon()
    # Split the group (conversation seating) from the rest: in the shifted case the dining keeps a real
    # WALKWAY off the GROUP (so its group-side chairs don't crowd the sofa) but only the standard ring
    # gap off other pieces (console, plant), which don't need a walk-past.
    _GROUP = {"sofa", "rug", "coffee_table", "accent_chair", "chaise", "side_table"}
    group_union = unary_union(
        [item_polygon(i.x, i.y, p.width_cm, p.depth_cm, i.rotation_deg) for i, p in placed if placement_group(p.category) in _GROUP]
    ) if placed else Polygon()
    other_blockers = unary_union(
        [item_polygon(i.x, i.y, p.width_cm, p.depth_cm, i.rotation_deg).buffer(25.0) for i, p in placed if placement_group(p.category) not in _GROUP]
    ) if placed else Polygon()
    pclear = prep(clear)

    seat_pts = [
        (it.x, it.y)
        for it, pr in placed
        if placement_group(pr.category)
        in {"sofa", "rug", "coffee_table", "accent_chair", "chaise", "side_table"}
    ]
    if seat_pts:
        sx = sum(p[0] for p in seat_pts) / len(seat_pts)
        sy = sum(p[1] for p in seat_pts) / len(seat_pts)
    else:
        c = analysis.polygon.centroid
        sx, sy = c.x, c.y

    minx, miny, maxx, maxy = analysis.polygon.bounds

    # In a GREAT room the conversation group is floated/shifted, freeing a large open block; the dining
    # belongs in the CENTRE of that block, not jammed into the farthest corner. Compute it orientation-
    # agnostically: the CENTROID of the largest OPEN region = the clear floor minus the group (buffered by
    # a walkway) minus other pieces. This works whichever wall the group faces. Small rooms (< great-room
    # floor) keep the legacy farthest-from-seating objective, so their dining goldens are byte-identical.
    target: Vec | None = None
    if _find_placed(placed, "sofa") is not None and analysis.area_cm2 >= GREAT_ROOM_MIN_CM2:
        # Use the RAW room minus the group (not the corridor-subtracted `clear`) so the centroid marks
        # the middle of the open block and isn't skewed toward a corner by a door corridor cut out of one
        # side. The scan below still enforces the real clear/disjoint placement.
        open_region = analysis.polygon.difference(group_union.buffer(_DINING_GROUP_WALKWAY_CM))
        biggest = largest_piece(open_region)
        if biggest is not None and biggest.area > tw * td * 1.2:
            c = biggest.centroid
            tx, ty = c.x, c.y
            # Align the dining LATERALLY behind the primary sofa (centred on the sofa's width) instead of
            # biasing it toward a far corner - a clean BACK-TO-BACK block reads INTENTIONAL, not shoved off
            # to one side. Keep the behind-distance from the open-region centroid; zero only the sideways
            # offset. The scan below still picks the nearest VALID pocket, so it naturally falls back to an
            # offset spot when the aligned one is blocked (windows on the back wall, another piece, etc.).
            prim = _find_placed(placed, "sofa")
            if prim is not None:
                pit, _ppr = prim
                pf = front_vector(pit.rotation_deg)
                f_comp = dot((tx - pit.x, ty - pit.y), pf)  # how far behind the sofa the open centre is
                tx = pit.x + pf[0] * f_comp  # drop the lateral component -> aligned behind the sofa centre
                ty = pit.y + pf[1] * f_comp
            target = (tx, ty)

    step = 20.0
    best = None
    best_key: tuple | None = None
    # Try both orientations (long axis along x or y) so a narrow open strip can still hold a table.
    for rot in (0.0, 90.0):
        pw, pd = (tw, td) if rot == 0.0 else (td, tw)
        hw, hd = pw / 2.0, pd / 2.0
        cx = minx + hw
        while cx <= maxx - hw + 1e-6:
            cy = miny + hd
            while cy <= maxy - hd + 1e-6:
                rect = item_polygon(cx, cy, pw, pd, 0.0)
                # Reserve room for the CHAIR RING too, not just the table: the ring sits ~a chair off
                # each table edge, so test the table buffered by that ring reach against the seating -
                # otherwise a ring chair can clip the sofa / L-return even though the table itself clears.
                # Shifted (great-room) case: keep a real WALKWAY between the dining and the conversation
                # GROUP (so the group-side chairs aren't crammed against the sofa), letting the table sit
                # closer to the freed-side wall instead (chairs just inside it). Legacy dining keeps the
                # bare-table containment + the standard ring gap.
                if target is not None:
                    ok = (
                        pclear.contains(rect.buffer(_DINING_WALL_MIN_CM))  # chairs stay inside the room
                        and rect.buffer(_DINING_GROUP_WALKWAY_CM).disjoint(group_union)  # walkway off the group
                        and rect.buffer(_DINING_RING_CLEAR_CM).disjoint(other_blockers)  # ring gap off other pieces
                    )
                else:
                    ok = pclear.contains(rect) and rect.buffer(_DINING_RING_CLEAR_CM).disjoint(blockers)
                if ok:
                    if target is not None:
                        # shifted group: the pocket CLOSEST to the freed-block centre wins (centred in
                        # the open block, not cornered). Negate so 'greater key' = nearer the target.
                        dt = math.hypot(cx - target[0], cy - target[1])
                        key = (-round(dt, 1), -round(cx, 1), -round(cy, 1))
                    else:
                        # legacy: farthest-from-seating first; deterministic tie-break by position.
                        d = math.hypot(cx - sx, cy - sy)
                        key = (round(d, 1), -round(cx, 1), -round(cy, 1))
                    if best_key is None or key > best_key:
                        best_key = key
                        best = (cx, cy, pw, pd, rot)
                cy += step
            cx += step

    if best is None:
        return []
    cx, cy, pw, pd, rot = best
    piece = largest_piece(item_polygon(cx, cy, pw, pd, 0.0).intersection(clear))
    if piece is None:
        return []
    score = 0.7 + 0.3 * min(1.0, math.hypot(cx - sx, cy - sy) / 500.0)
    return [
        _frame_zone(
            "dining_table", 0, piece, score, rot, (cx, cy), (0.0, 1.0), (1.0, 0.0),
            pd, pw, [R_SEPARATE_DINING_ZONE, R_FLEXIBLE_SPOT], "dining_pocket", kind="free",
        )
    ]


def _dining_chair_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], stats: CategoryStats
) -> list[ZoneData]:
    """Dining chairs ringed around the placed dining TABLE, each turned to face it. Chairs sit
    just off the table edges (a small gap so they never overlap it beyond tolerance) distributed
    along the two long sides, scaling with the table (~4 chairs, up to ~6 for a long table). Each
    candidate is a small free zone; the caller's per-anchor loop validates every one and simply
    SKIPS any that can't fit (e.g. a side crowded against a wall) — fewer chairs is fine. No table
    placed -> [] -> no chairs (never orphaned)."""
    table = _find_placed(placed, "dining_table")
    if table is None:
        return []
    item, product = table
    f = front_vector(item.rotation_deg)  # table depth axis
    w = width_axis(item.rotation_deg)  # table width axis
    half_w = product.width_cm / 2.0
    half_d = product.depth_cm / 2.0

    cs = stats.get("accent_chair", {})
    chair = max(45.0, min(cs.get("min_w", 55.0), 60.0))  # a dining-chair-sized footprint
    gap = 8.0  # keep the chair a hair off the table edge (no overlap beyond tolerance)

    # Chairs per long side scale with the table width: 2 for a normal table, 3 for a long one.
    per_side = max(2, min(3, int(round(product.width_cm / 75.0))))
    span = product.width_cm - chair - 10.0  # usable width for chair centres along the long edge
    laterals = (
        [(-0.5 + i / (per_side - 1)) * span for i in range(per_side)]
        if span > 0.0 and per_side > 1
        else [0.0]
    )

    # Candidate ring positions as (centre, ...): the two LONG sides (offset along ±f, spread along
    # w) plus one head/foot chair at each SHORT end (offset along ±w, centred). Long sides first so
    # a max cap keeps the fuller sides; every candidate is gated by the caller and skipped if unfit.
    spots: list[Vec] = []
    long_off = half_d + gap + chair / 2.0
    for side in (1.0, -1.0):
        base = add((item.x, item.y), f, side * long_off)
        for lat in laterals:
            spots.append(add(base, w, lat))
    short_off = half_w + gap + chair / 2.0
    for side in (1.0, -1.0):  # head + foot of the table
        spots.append(add((item.x, item.y), w, side * short_off))

    zones: list[ZoneData] = []
    for idx, (cx, cy) in enumerate(spots):
        rot = math.degrees(math.atan2(-(item.x - cx), item.y - cy))  # face the table centre
        piece = largest_piece(item_polygon(cx, cy, chair, chair, rot).intersection(analysis.polygon))
        if piece is None:
            continue
        zones.append(
            _frame_zone(
                "accent_chair", idx, piece, 0.8, rot, (cx, cy), (0.0, 1.0), (1.0, 0.0),
                chair, chair, [R_FACES_DINING_TABLE], f"dining_chair_{idx}", kind="free",
            )
        )
    return zones


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
    gen = _GENERATORS.get(category)
    return gen(analysis, placed, stats) if gen else []


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
        w = product.width_cm / max(zone.lat_len, 1.0)
        # For a RUG, fill BOTH dimensions - reward the TIGHTER of width/depth, so a thin runner that fills
        # the width but not the depth (e.g. a 300x100 rug in a 660x280 conversation-zone frame) is NOT
        # treated the same as a proper area rug that fills the depth too. Width-only ignored depth entirely,
        # tying a runner with a full-size rug and letting colour/order pick the runner. Scoped to the rug so
        # other frame pieces (the coffee table) keep the original width-based fit - no golden churn there.
        if placement_group(product.category) == "rug":
            return min(w, product.depth_cm / max(zone.fwd_len, 1.0))
        return w
    return min(1.5, (product.width_cm * product.depth_cm) / max(zone.polygon.area, 1.0))
