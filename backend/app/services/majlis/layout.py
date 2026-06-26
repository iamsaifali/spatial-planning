"""Majlis perimeter-seating placement (deterministic).

The Majlis layout lines every wall with sofas facing the open centre, filling each wall
until no module fits. This module is SELF-CONTAINED and only READS the shared, cached
`RoomAnalysis` (walls, clear runs, swing arcs, polygon) - it never mutates it.

Geometry conventions match the family engine: a seat is `item_polygon(x, y, width, depth,
rotation)` with `rotation = rotation_for_normal(wall.normal)`, so its back sits on the wall
and its front faces inward (`width` runs along the wall, `depth` into the room).
"""

from dataclasses import dataclass

from shapely.geometry import Polygon

from app.services.spatial.core import RoomAnalysis, WallData
from app.services.spatial.geometry_utils import (
    add,
    item_polygon,
    rotation_for_normal,
)

# Default seating modules (cm). Real per-slot product selection is wired in a later phase;
# these representative widths drive the packing geometry. Widest-first packing.
DEFAULT_MODULE_WIDTHS: tuple[float, ...] = (226.0, 186.0, 158.0)
DEFAULT_DEPTH = 95.0
WALL_GAP = 4.0          # clearance between a sofa back and the wall
SEAT_GAP = 14.0         # gap between adjacent sofas on the same wall
CORNER_RESERVE_EXTRA = 10.0  # added to depth at true corners so perpendicular sofas clear
SEAT_WIDTH_CM = 75.0    # nominal width per person, for seat counting
SWING_OVERLAP_RATIO = 0.05  # skip a module that clips a door swing arc by more than this


@dataclass(frozen=True)
class SeatPlacement:
    """One placed perimeter sofa."""
    wall_index: int
    x: float
    y: float
    rotation_deg: float
    width_cm: float
    depth_cm: float
    seats: int

    def polygon(self) -> Polygon:
        return item_polygon(self.x, self.y, self.width_cm, self.depth_cm, self.rotation_deg)


def _seats_for(width_cm: float) -> int:
    return max(1, round(width_cm / SEAT_WIDTH_CM))


def _pack_run(run_len: float, modules: tuple[float, ...]) -> list[float]:
    """Fill `run_len` to MAXIMISE wall coverage (the majlis goal): first fit the most
    modules that physically fit (n smallest + gaps), then upgrade each slot to the widest
    module the remaining budget allows. Returns the chosen widths (caller centres the row)."""
    smallest = min(modules)
    # most modules that fit with SEAT_GAP between them
    n = 0
    while (n + 1) * smallest + n * SEAT_GAP <= run_len:
        n += 1
    if n == 0:
        return []
    budget = run_len - (n - 1) * SEAT_GAP  # width available for the modules themselves
    chosen = [smallest] * n
    used = smallest * n
    improved = True
    while improved:  # greedily widen slots while the budget allows
        improved = False
        for i in range(n):
            for w in sorted(modules, reverse=True):
                if w > chosen[i] and used - chosen[i] + w <= budget:
                    used += w - chosen[i]
                    chosen[i] = w
                    improved = True
                    break
    return chosen


def fill_perimeter(
    analysis: RoomAnalysis,
    module_widths: tuple[float, ...] = DEFAULT_MODULE_WIDTHS,
    depth: float = DEFAULT_DEPTH,
) -> list[SeatPlacement]:
    """Place sofas along every wall, facing the open centre, until the walls are full."""
    corner_reserve = depth + CORNER_RESERVE_EXTRA
    smallest = min(module_widths)
    placed: list[SeatPlacement] = []
    placed_polys: list[Polygon] = []
    swing_arcs = list(analysis.swing_arcs.values())
    room_buffered = analysis.polygon.buffer(1.5)

    for wall in analysis.walls:
        rotation = rotation_for_normal(wall.normal)
        for a, b in wall.clear_floor:
            # reserve the corner at any run end that meets a true wall corner (0 or length),
            # so a sofa here can't collide with a perpendicular sofa on the adjacent wall.
            lo = a + (corner_reserve if a <= 1.0 else SEAT_GAP)
            hi = b - (corner_reserve if b >= wall.length - 1.0 else SEAT_GAP)
            run = hi - lo
            if run < smallest:
                continue

            widths = _pack_run(run, module_widths)
            if not widths:
                continue
            total = sum(widths) + SEAT_GAP * (len(widths) - 1)
            t = lo + max(0.0, (run - total) / 2.0)  # centre the seating row on the wall

            for w in widths:
                center_t = t + w / 2.0
                cx, cy = add(wall.point_at(center_t), wall.normal, depth / 2.0 + WALL_GAP)
                poly = item_polygon(cx, cy, w, depth, rotation)
                if not _placeable(poly, room_buffered, placed_polys, swing_arcs):
                    t += w + SEAT_GAP
                    continue
                placed.append(
                    SeatPlacement(wall.index, round(cx, 1), round(cy, 1), rotation, w, depth, _seats_for(w))
                )
                placed_polys.append(poly)
                t += w + SEAT_GAP
    return placed


def _placeable(poly: Polygon, room_buffered: Polygon, others: list[Polygon], arcs: list[Polygon]) -> bool:
    """A module is placeable if it stays in-bounds, clears door swings, and doesn't overlap
    an already-placed sofa (corner reserves usually prevent this, but stay defensive)."""
    if poly.difference(room_buffered).area > 0.01 * poly.area:
        return False
    for arc in arcs:
        if poly.intersection(arc).area > SWING_OVERLAP_RATIO * arc.area:
            return False
    for op in others:
        inter = poly.intersection(op)
        if not inter.is_empty and inter.area > 0.02 * min(poly.area, op.area):
            return False
    return True


def total_seats(placements: list[SeatPlacement]) -> int:
    return sum(p.seats for p in placements)
