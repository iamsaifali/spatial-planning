"""Majlis accessories: a grounding central rug plus corner pieces (side tables for
serving, floor lamps, plants) tucked into the open corners the perimeter seating leaves.

Deterministic and self-contained: reads the shared RoomAnalysis, never mutates it. Real
per-item product selection is wired in a later phase; representative default sizes here
drive the geometry.
"""

from dataclasses import dataclass

from shapely.geometry import Polygon

from app.services.majlis.layout import SeatPlacement
from app.services.spatial.core import RoomAnalysis
from app.services.spatial.geometry_utils import add, item_polygon, unit

WALKABLE = {"rug"}

# representative accessory footprints (cm); product selection refines these later
SIDE_TABLE = 55.0
LAMP = 40.0
PLANT = 45.0
CORNER_MARGIN = 14.0
# rug fills a share of the room, capped so it grounds the centre without reaching the walls
RUG_ROOM_FRACTION = 0.6
RUG_MAX_W = 420.0
RUG_MAX_D = 320.0
# the corners cycle through these, in order, around the room
CORNER_CATEGORIES = ("side_table", "lighting", "side_table", "decor")
_CORNER_SIZE = {"side_table": SIDE_TABLE, "lighting": LAMP, "decor": PLANT}


@dataclass(frozen=True)
class MajlisAccessory:
    category: str
    x: float
    y: float
    rotation_deg: float
    width_cm: float
    depth_cm: float

    def polygon(self) -> Polygon:
        return item_polygon(self.x, self.y, self.width_cm, self.depth_cm, self.rotation_deg)


def central_rug(analysis: RoomAnalysis) -> MajlisAccessory | None:
    """One large rug centred in the open middle, grounding the seating ring."""
    minx, miny, maxx, maxy = analysis.polygon.bounds
    rug_w = min(RUG_ROOM_FRACTION * (maxx - minx), RUG_MAX_W)
    rug_d = min(RUG_ROOM_FRACTION * (maxy - miny), RUG_MAX_D)
    if rug_w < 120.0 or rug_d < 90.0:
        return None  # room too small for a meaningful central rug
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    return MajlisAccessory("rug", round(cx, 1), round(cy, 1), 0.0, round(rug_w, 1), round(rug_d, 1))


def corner_accessories(
    analysis: RoomAnalysis, sofas: list[SeatPlacement]
) -> list[MajlisAccessory]:
    """Place one piece in each open corner, angled along the corner diagonal; skip a corner
    whose piece would hit a door swing or a sofa (corner reserves usually keep it clear)."""
    sofa_polys = [s.polygon() for s in sofas]
    arcs = list(analysis.swing_arcs.values())
    room_buffered = analysis.polygon.buffer(1.5)
    verts = analysis.room.vertices
    n = len(verts)
    out: list[MajlisAccessory] = []
    for i in range(n):
        prev_wall = analysis.walls[(i - 1) % n]
        next_wall = analysis.walls[i % n]
        diag = unit(prev_wall.normal[0] + next_wall.normal[0], prev_wall.normal[1] + next_wall.normal[1])
        if diag == (0.0, 0.0):
            continue
        category = CORNER_CATEGORIES[i % len(CORNER_CATEGORIES)]
        size = _CORNER_SIZE[category]
        cx, cy = add(verts[i], diag, size / 2.0 + CORNER_MARGIN)
        poly = item_polygon(cx, cy, size, size, 0.0)
        if not _clear(poly, room_buffered, sofa_polys, arcs):
            continue
        out.append(MajlisAccessory(category, round(cx, 1), round(cy, 1), 0.0, size, size))
    return out


def build_accessories(
    analysis: RoomAnalysis, sofas: list[SeatPlacement]
) -> list[MajlisAccessory]:
    """Full accessory set: central rug + corner pieces."""
    items: list[MajlisAccessory] = []
    rug = central_rug(analysis)
    if rug is not None:
        items.append(rug)
    items.extend(corner_accessories(analysis, sofas))
    return items


def _clear(poly: Polygon, room_buffered: Polygon, sofas: list[Polygon], arcs: list[Polygon]) -> bool:
    if poly.difference(room_buffered).area > 0.01 * poly.area:
        return False
    for arc in arcs:
        if poly.intersection(arc).area > 0.05 * arc.area:
            return False
    for sp in sofas:
        inter = poly.intersection(sp)
        if not inter.is_empty and inter.area > 0.02 * min(poly.area, sp.area):
            return False
    return True
