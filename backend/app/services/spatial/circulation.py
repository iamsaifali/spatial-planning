"""Entry points and circulation corridors."""

from shapely.geometry import LineString, Polygon

from app.models.geometry import Room
from app.services.spatial.core import CorridorData, EntryData, WallData
from app.services.spatial.geometry_utils import Vec, add, dist, largest_piece

CORRIDOR_HALF_WIDTH = 40.0  # 80 cm corridors
ENTRY_INSET_CM = 30.0

CORRIDOR_UNRESOLVED = "CORRIDOR_UNRESOLVED"


def build_entries(room: Room, walls: list[WallData]) -> list[EntryData]:
    entries: list[EntryData] = []
    widest: tuple[float, int] | None = None
    for i, door in enumerate(room.doors):
        wall = walls[door.wall_index]
        mid_t = door.offset_cm + door.width_cm / 2.0
        point = add(wall.point_at(mid_t), wall.normal, ENTRY_INSET_CM)
        entries.append(EntryData(door_id=door.id, point=point))
        if widest is None or door.width_cm > widest[0]:
            widest = (door.width_cm, i)
    if widest is not None:
        entries[widest[1]].is_primary = True
    return entries


def interior_anchor(poly: Polygon) -> Vec:
    """Pole of inaccessibility (most interior point) with a safe fallback."""
    try:
        from shapely.ops import polylabel

        p = polylabel(poly, tolerance=10)
        if poly.contains(p):
            return (p.x, p.y)
    except Exception:
        pass
    rp = poly.representative_point()
    return (rp.x, rp.y)


def _corridor(
    poly: Polygon, anchor: Vec, a: Vec, b: Vec, cid: str, from_label: str, to_label: str
) -> CorridorData | None:
    if dist(a, b) < 10.0:
        return None
    interior = poly.buffer(1.0)  # tolerance so boundary-touching paths count
    path = LineString([a, b])
    if not interior.covers(path):
        path = LineString([a, anchor, b])
        if not interior.covers(path):
            return None
    corridor_poly = largest_piece(
        path.buffer(CORRIDOR_HALF_WIDTH, cap_style="flat").intersection(poly)
    )
    if corridor_poly is None or corridor_poly.area < 100.0:
        return None
    return CorridorData(
        id=cid, from_label=from_label, to_label=to_label, a=a, b=b, path=path, polygon=corridor_poly
    )


def build_corridors(poly: Polygon, entries: list[EntryData], anchor: Vec) -> tuple[list[CorridorData], list[str]]:
    corridors: list[CorridorData] = []
    notices: list[str] = []
    if not entries:
        return corridors, notices

    primary = next((e for e in entries if e.is_primary), entries[0])
    c = _corridor(
        poly, anchor, primary.point, anchor, "corridor-entry-center",
        f"door:{primary.door_id}", "center",
    )
    if c is not None:
        corridors.append(c)
    else:
        notices.append(CORRIDOR_UNRESOLVED)

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            c = _corridor(
                poly, anchor, entries[i].point, entries[j].point,
                f"corridor-{entries[i].door_id}-{entries[j].door_id}",
                f"door:{entries[i].door_id}", f"door:{entries[j].door_id}",
            )
            if c is not None:
                corridors.append(c)
            else:
                notices.append(CORRIDOR_UNRESOLVED)

    return corridors, notices
