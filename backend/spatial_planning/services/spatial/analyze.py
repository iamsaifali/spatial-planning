"""Room analysis orchestrator with LRU caching by canonical room hash."""

from shapely.prepared import prep

from spatial_planning.config import get_settings
from spatial_planning.models.geometry import Room
from spatial_planning.services.spatial.cache import LRUCache
from spatial_planning.services.spatial.circulation import build_corridors, build_entries, interior_anchor
from spatial_planning.services.spatial.core import RoomAnalysis
from spatial_planning.services.spatial.geometry_utils import dot
from spatial_planning.services.spatial.hashing import room_hash
from spatial_planning.services.spatial.keepout import build_keepout, keep_clear_union
from spatial_planning.services.spatial.normalize import require_valid_room
from spatial_planning.services.spatial.walls import build_walls, longest_clear_wall_index

_cache: LRUCache[RoomAnalysis] = LRUCache(get_settings().analysis_cache_size)


def _focal_wall(analysis_walls, longest_idx: int | None) -> int | None:
    candidates = []
    for wall in analysis_walls:
        solid = max((b - a for a, b in wall.clear_solid), default=0.0)
        if solid >= 150.0:
            candidates.append((solid, wall.index))
    if not candidates:
        return None
    if longest_idx is not None:
        longest_wall = analysis_walls[longest_idx]
        opposite = [
            (solid, idx)
            for solid, idx in candidates
            if idx != longest_idx and dot(analysis_walls[idx].normal, longest_wall.normal) < -0.5
        ]
        if opposite:
            best = max(opposite)
            analysis_walls[best[1]].is_focal = True
            return best[1]
    best = max(candidates)
    analysis_walls[best[1]].is_focal = True
    return best[1]


def analyze_room(room: Room) -> RoomAnalysis:
    h = room_hash(room)
    cached = _cache.get(h)
    if cached is not None:
        return cached

    poly = require_valid_room(room)
    prepared = prep(poly)
    walls, notices = build_walls(room, poly, prepared)
    longest_idx = longest_clear_wall_index(walls)
    swing_arcs, entry_clearances, window_strips = build_keepout(room, walls, poly)
    kc = keep_clear_union(swing_arcs, entry_clearances)
    entries = build_entries(room, walls)
    anchor = interior_anchor(poly)
    corridors, corridor_notices = build_corridors(poly, entries, anchor)
    usable = poly.difference(kc)
    focal_idx = _focal_wall(walls, longest_idx)

    analysis = RoomAnalysis(
        room=room,
        polygon=poly,
        prepared=prepared,
        walls=walls,
        entries=entries,
        swing_arcs=swing_arcs,
        entry_clearances=entry_clearances,
        window_strips=window_strips,
        keep_clear_union=kc,
        corridors=corridors,
        usable_area=usable,
        interior_anchor=anchor,
        focal_wall_index=focal_idx,
        longest_clear_wall_index=longest_idx,
        analysis_hash=h,
        notices=notices + corridor_notices,
    )
    _cache.put(h, analysis)
    return analysis


def clear_cache() -> None:
    _cache.clear()
