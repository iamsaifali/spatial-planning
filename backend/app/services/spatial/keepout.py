"""Keep-clear geometry: door swing arcs, entry clearances, window strips."""

import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from app.models.geometry import Room, Window
from app.services.spatial.core import WallData
from app.services.spatial.geometry_utils import add, largest_piece, quad

ENTRY_CLEARANCE_CM = 60.0
WINDOW_STRIP_CM = 40.0
ARC_SEGMENTS = 12


def door_swing_arc(wall: WallData, offset: float, width: float, hinge: str, room_poly: Polygon) -> Polygon | None:
    """Quarter-disc the door sweeps through, clipped to the room."""
    a = wall.point_at(offset)
    b = wall.point_at(offset + width)
    hinge_pt, other = (a, b) if hinge == "left" else (b, a)
    d = ((other[0] - hinge_pt[0]) / width, (other[1] - hinge_pt[1]) / width)
    n = wall.normal
    pts = [hinge_pt]
    for i in range(ARC_SEGMENTS + 1):
        t = (math.pi / 2.0) * i / ARC_SEGMENTS
        pts.append(
            (
                hinge_pt[0] + width * (d[0] * math.cos(t) + n[0] * math.sin(t)),
                hinge_pt[1] + width * (d[1] * math.cos(t) + n[1] * math.sin(t)),
            )
        )
    arc = Polygon(pts)
    if not arc.is_valid:
        arc = arc.buffer(0)
    clipped = largest_piece(arc.intersection(room_poly))
    return clipped if clipped is not None and clipped.area > 1.0 else None


def _strip(wall: WallData, offset: float, width: float, depth: float, room_poly: Polygon) -> Polygon | None:
    p1 = wall.point_at(offset)
    p2 = wall.point_at(offset + width)
    p3 = add(p2, wall.normal, depth)
    p4 = add(p1, wall.normal, depth)
    clipped = largest_piece(quad(p1, p2, p3, p4).intersection(room_poly))
    return clipped if clipped is not None and clipped.area > 1.0 else None


def build_keepout(
    room: Room, walls: list[WallData], room_poly: Polygon
) -> tuple[dict[str, Polygon], dict[str, Polygon], dict[str, tuple[Polygon, float]]]:
    swing_arcs: dict[str, Polygon] = {}
    entry_clearances: dict[str, Polygon] = {}
    window_strips: dict[str, tuple[Polygon, float]] = {}

    for door in room.doors:
        wall = walls[door.wall_index]
        if door.swing == "inward":
            arc = door_swing_arc(wall, door.offset_cm, door.width_cm, door.hinge, room_poly)
            if arc is not None:
                swing_arcs[door.id] = arc
        clearance = _strip(wall, door.offset_cm, door.width_cm, ENTRY_CLEARANCE_CM, room_poly)
        if clearance is not None:
            entry_clearances[door.id] = clearance

    for win in room.windows:
        wall = walls[win.wall_index]
        strip = _strip(wall, win.offset_cm, win.width_cm, WINDOW_STRIP_CM, room_poly)
        if strip is not None:
            window_strips[win.id] = (strip, win.sill_height_cm)

    return swing_arcs, entry_clearances, window_strips


def keep_clear_union(swing_arcs: dict[str, Polygon], entry_clearances: dict[str, Polygon]):
    geoms = list(swing_arcs.values()) + list(entry_clearances.values())
    return unary_union(geoms) if geoms else Polygon()


def window_sill(room: Room, window_id: str) -> Window | None:
    return next((w for w in room.windows if w.id == window_id), None)
