"""Wall extraction: lengths, inward normals, opening spans, clear segments."""

import math

from shapely.geometry import Point, Polygon
from shapely.prepared import PreparedGeometry

from app.models.geometry import Room
from app.services.spatial.core import OpeningData, WallData
from app.services.spatial.geometry_utils import (
    Vec,
    add,
    merge_intervals,
    perp,
    subtract_intervals,
    unit,
)

DOOR_JAMB_MARGIN = 10.0  # cm kept free beside door openings for floor furniture


def _inward_normal(poly: Polygon, prepared: PreparedGeometry, mid: Vec, d: Vec) -> Vec:
    """Empirically pick the perpendicular that points into the room."""
    cand_a = perp(d)
    cand_b = (-cand_a[0], -cand_a[1])
    for dist_cm in (2.0, 5.0, 10.0, 20.0):
        in_a = prepared.contains(Point(add(mid, cand_a, dist_cm)))
        in_b = prepared.contains(Point(add(mid, cand_b, dist_cm)))
        if in_a and not in_b:
            return cand_a
        if in_b and not in_a:
            return cand_b
    # Degenerate (very thin room): point toward the polygon's interior point.
    rp = poly.representative_point()
    to_interior = unit(rp.x - mid[0], rp.y - mid[1])
    return cand_a if (cand_a[0] * to_interior[0] + cand_a[1] * to_interior[1]) >= 0 else cand_b


def build_walls(room: Room, poly: Polygon, prepared: PreparedGeometry) -> tuple[list[WallData], list[str]]:
    notices: list[str] = []
    n = len(room.vertices)
    walls: list[WallData] = []

    for i in range(n):
        a = room.vertices[i]
        b = room.vertices[(i + 1) % n]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        d = unit(b[0] - a[0], b[1] - a[1])
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        normal = _inward_normal(poly, prepared, mid, d)
        walls.append(WallData(index=i, start=a, end=b, length=length, dir=d, normal=normal))

    for kind, openings in (("door", room.doors), ("window", room.windows)):
        for op in openings:
            wall = walls[op.wall_index]
            wall.openings.append(
                OpeningData(kind=kind, id=op.id, a=op.offset_cm, b=op.offset_cm + op.width_cm)
            )

    for wall in walls:
        wall.openings.sort(key=lambda o: o.a)
        door_spans = [(o.a, o.b) for o in wall.openings if o.kind == "door"]
        all_spans = [(o.a, o.b) for o in wall.openings]
        merged_doors = merge_intervals(door_spans)
        merged_all = merge_intervals(all_spans)
        if len(merged_all) < len(all_spans):
            notices.append(f"Overlapping openings on wall {wall.index} were treated as one span.")
        door_blocks = [(a - DOOR_JAMB_MARGIN, b + DOOR_JAMB_MARGIN) for a, b in merged_doors]
        wall.clear_floor = subtract_intervals(wall.length, door_blocks, min_keep=20.0)
        wall.clear_solid = subtract_intervals(wall.length, merged_all, min_keep=20.0)

    return walls, notices


def longest_clear_wall_index(walls: list[WallData]) -> int | None:
    """Wall holding the longest clear-floor segment."""
    best: tuple[float, int] | None = None
    for wall in walls:
        for a, b in wall.clear_floor:
            seg = b - a
            if best is None or seg > best[0] + 1e-9:
                best = (seg, wall.index)
    if best is None:
        return None
    walls[best[1]].is_longest_clear = True
    return best[1]
