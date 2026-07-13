"""Deterministic minimal-displacement auto-fix and placement suggestion."""

import math
from collections.abc import Iterator

from shapely.geometry import Polygon

from spatial_planning.models.geometry import PlacedItem, Pose
from spatial_planning.models.products import Product
from spatial_planning.models.validation import MUST_FIX_CODES, AutoFix, BetterPlacement, Finding
from spatial_planning.services.spatial.core import RoomAnalysis, ZoneData
from spatial_planning.services.spatial.geometry_utils import add, dist, item_polygon, sub, unit
from spatial_planning.services.spatial.validate import PlacedProduct, build_poly, must_fix_only
from spatial_planning.services.spatial.zones import CategoryStats, anchor_pose, fits_zone, zones_for_category

MAX_TESTS = 1400


def _wall_slide_candidates(analysis: RoomAnalysis, item: PlacedItem, product: Product) -> Iterator[Pose]:
    """Slide along the nearest wall while keeping offset and rotation."""
    best_wall = None
    best_d = math.inf
    for wall in analysis.walls:
        # distance from item center to the wall segment
        t = (item.x - wall.start[0]) * wall.dir[0] + (item.y - wall.start[1]) * wall.dir[1]
        t = min(max(t, 0.0), wall.length)
        p = wall.point_at(t)
        d = dist((item.x, item.y), p)
        if d < best_d:
            best_d, best_wall = d, wall
    if best_wall is None or best_d > product.depth_cm / 2.0 + 30.0:
        return
    for step in range(1, 41):
        for sign in (1.0, -1.0):
            delta = sign * step * 5.0
            yield Pose(
                x=item.x + best_wall.dir[0] * delta,
                y=item.y + best_wall.dir[1] * delta,
                rotation_deg=item.rotation_deg,
            )


def _push_out_candidates(
    analysis: RoomAnalysis,
    other_polys: list[tuple[PlacedItem, Product, Polygon]],
    item: PlacedItem,
    poly: Polygon,
) -> Iterator[Pose]:
    """Move away from whatever the item currently intersects."""
    obstacles = [op for _i, _p, op in other_polys if poly.intersects(op)]
    obstacles += [arc for arc in analysis.swing_arcs.values() if poly.intersects(arc)]
    outside = poly.difference(analysis.polygon)
    if not outside.is_empty:
        obstacles.append(outside)
    for obstacle in obstacles:
        inter = poly.intersection(obstacle)
        target = inter if not inter.is_empty else obstacle
        c = target.centroid
        v = unit(*sub((item.x, item.y), (c.x, c.y)))
        if v == (0.0, 0.0):
            v = (0.0, -1.0)
        for step in range(1, 21):
            p = add((item.x, item.y), v, step * 5.0)
            yield Pose(x=p[0], y=p[1], rotation_deg=item.rotation_deg)


def _spiral_candidates(item: PlacedItem) -> Iterator[Pose]:
    rotations = [
        item.rotation_deg,
        (item.rotation_deg + 90.0) % 360.0,
        (item.rotation_deg - 90.0) % 360.0,
        (item.rotation_deg + 180.0) % 360.0,
    ]
    for ring in range(1, 16):
        r = ring * 10.0
        for k in range(16):
            ang = 2.0 * math.pi * k / 16.0
            x = item.x + r * math.cos(ang)
            y = item.y + r * math.sin(ang)
            for rot in rotations:
                yield Pose(x=x, y=y, rotation_deg=rot)


def find_autofix(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    item: PlacedItem,
    product: Product,
    findings: list[Finding],
) -> AutoFix | None:
    must_fix = [f.code for f in findings if f.code in MUST_FIX_CODES]
    if not must_fix:
        return None

    other_polys = [(i, p, build_poly(i, p)) for i, p in placed if i.instance_id != item.instance_id]
    room_buffered = analysis.polygon.buffer(1.5)
    poly = build_poly(item, product)

    def valid(pose: Pose) -> bool:
        candidate_poly = item_polygon(pose.x, pose.y, product.width_cm, product.depth_cm, pose.rotation_deg)
        return must_fix_only(analysis, other_polys, product, candidate_poly, room_buffered)

    tested = 0
    for gen in (
        _wall_slide_candidates(analysis, item, product),
        _push_out_candidates(analysis, other_polys, item, poly),
        _spiral_candidates(item),
    ):
        for pose in gen:
            tested += 1
            if tested > MAX_TESTS:
                return None
            if valid(pose):
                return AutoFix(
                    pose=Pose(x=round(pose.x, 1), y=round(pose.y, 1), rotation_deg=pose.rotation_deg),
                    resolves=sorted(set(must_fix)),
                )
    return None


def settle_pose(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    product: Product,
    pose: Pose,
    instance_id: str = "__candidate__",
) -> Pose:
    """Anchor pose nudged to the nearest error-free spot (small local search)."""
    other_polys = [(i, p, build_poly(i, p)) for i, p in placed if i.instance_id != instance_id]
    room_buffered = analysis.polygon.buffer(1.5)

    def valid(p: Pose) -> bool:
        cand = item_polygon(p.x, p.y, product.width_cm, product.depth_cm, p.rotation_deg)
        return must_fix_only(analysis, other_polys, product, cand, room_buffered)

    WALL_GAP = 2.0  # keep every item this far off the wall - matches the wall-band offset, so nothing
    #                 renders flush against (or crossing) a drawn wall. An item further in is untouched.

    def wall_clearance(p: Pose) -> float:
        ip = item_polygon(p.x, p.y, product.width_cm, product.depth_cm, p.rotation_deg)
        minx, miny, maxx, maxy = ip.bounds
        rminx, rminy, rmaxx, rmaxy = analysis.polygon.bounds
        return min(minx - rminx, miny - rminy, rmaxx - maxx, rmaxy - maxy)  # <0 = crosses a wall

    def settle_inside(p: Pose) -> Pose:
        # Hard guarantee: an item must NEVER cross a wall, and never sit flush against one either
        # (the frontend draws wall thickness over a flush item). Nudge any item within WALL_GAP of a
        # wall (or outside) inward to that gap; items already comfortably inside are left as-is.
        if wall_clearance(p) >= WALL_GAP - 0.1:
            return p
        ip = item_polygon(p.x, p.y, product.width_cm, product.depth_cm, p.rotation_deg)
        minx, miny, maxx, maxy = ip.bounds
        rminx, rminy, rmaxx, rmaxy = analysis.polygon.bounds
        dx = (rmaxx - WALL_GAP - maxx) if (rmaxx - maxx) < WALL_GAP else ((rminx + WALL_GAP - minx) if (minx - rminx) < WALL_GAP else 0.0)
        dy = (rmaxy - WALL_GAP - maxy) if (rmaxy - maxy) < WALL_GAP else ((rminy + WALL_GAP - miny) if (miny - rminy) < WALL_GAP else 0.0)
        moved = Pose(x=round(p.x + dx, 1), y=round(p.y + dy, 1), rotation_deg=p.rotation_deg)
        if valid(moved):
            return moved
        # the straight nudge overlaps a neighbour: spiral from it for a spot that is BOTH off the wall
        # and overlap-free; failing that, keep it inside anyway (a small overlap beats crossing a wall).
        probe2 = PlacedItem(instance_id=instance_id, product_id=product.id, x=moved.x, y=moved.y, rotation_deg=moved.rotation_deg)
        for c in _spiral_candidates(probe2):
            cp = Pose(x=round(c.x, 1), y=round(c.y, 1), rotation_deg=c.rotation_deg)
            if wall_clearance(cp) >= WALL_GAP - 0.1 and valid(cp):
                return cp
        return moved

    if valid(pose):
        return settle_inside(pose)
    probe = PlacedItem(
        instance_id=instance_id, product_id=product.id,
        x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg,
    )
    for candidate in _spiral_candidates(probe):
        if dist((candidate.x, candidate.y), (pose.x, pose.y)) > 80.0:
            continue
        if valid(candidate):
            return settle_inside(Pose(x=round(candidate.x, 1), y=round(candidate.y, 1), rotation_deg=candidate.rotation_deg))
    return settle_inside(pose)


def find_better_placement(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    item: PlacedItem,
    product: Product,
    stats: CategoryStats,
) -> BetterPlacement | None:
    others = [(i, p) for i, p in placed if i.instance_id != item.instance_id]
    zones = zones_for_category(product.category, analysis, others, stats)
    for zone in zones:
        if not fits_zone(zone, product, margin=1.05):
            continue
        pose = settle_pose(analysis, others, product, anchor_pose(zone, product, analysis), item.instance_id)
        # offering the spot the item already occupies is pointless
        if dist((pose.x, pose.y), (item.x, item.y)) < 25.0:
            continue
        return BetterPlacement(pose=pose, zone_id=zone.id)
    return None


def suggest_pose(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    product: Product,
    stats: CategoryStats,
    zone_id: str | None = None,
    room_type: str | None = None,
) -> tuple[Pose, str | None, list[Pose]]:
    # room_type is threaded through so Majlis poses anchor to the same perimeter /
    # centre zones the selector chose; defaults to None -> living-room behaviour.
    zones = zones_for_category(product.category, analysis, placed, stats, room_type=room_type)
    chosen: ZoneData | None = None
    if zone_id is not None:
        chosen = next((z for z in zones if z.id == zone_id), None)
    if chosen is None:
        chosen = next((z for z in zones if fits_zone(z, product, margin=1.05)), None)
    if chosen is None and zones:
        chosen = zones[0]
    if chosen is None:
        c = analysis.usable_area.centroid if not analysis.usable_area.is_empty else analysis.polygon.centroid
        fallback = settle_pose(analysis, placed, product, Pose(x=round(c.x, 1), y=round(c.y, 1), rotation_deg=0))
        return fallback, None, []

    pose = settle_pose(analysis, placed, product, anchor_pose(chosen, product, analysis))
    alternatives = [
        settle_pose(analysis, placed, product, anchor_pose(z, product, analysis))
        for z in zones
        if z.id != chosen.id and fits_zone(z, product, margin=1.05)
    ][:2]
    return pose, chosen.id, alternatives
