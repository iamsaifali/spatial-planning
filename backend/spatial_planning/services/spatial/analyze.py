"""Room analysis orchestrator with LRU caching by canonical room hash."""

from shapely.prepared import prep

from spatial_planning.config import get_settings
from spatial_planning.models.analysis import AnalysisResponse, RoomMetrics
from spatial_planning.models.geometry import Room
from spatial_planning.services.spatial.cache import LRUCache
from spatial_planning.services.spatial.circulation import build_corridors, build_entries, interior_anchor
from spatial_planning.services.spatial.core import RoomAnalysis, ZoneData
from spatial_planning.services.spatial.geometry_utils import dot, pieces_of, poly_pts
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


def to_response(analysis: RoomAnalysis, zones: list[ZoneData]) -> AnalysisResponse:
    poly = analysis.polygon
    minx, miny, maxx, maxy = poly.bounds
    return AnalysisResponse(
        analysis_hash=analysis.analysis_hash,
        metrics=RoomMetrics(
            area_m2=round(poly.area / 10_000.0, 2),
            perimeter_cm=round(poly.exterior.length, 1),
            bbox_w_cm=round(maxx - minx, 1),
            bbox_h_cm=round(maxy - miny, 1),
        ),
        walls=[w.to_model() for w in analysis.walls],
        entries=[e.to_model() for e in analysis.entries],
        keep_clear=[
            poly_pts(p)
            for p in pieces_of(analysis.keep_clear_union)
        ],
        window_strips=[poly_pts(strip) for strip, _sill in analysis.window_strips.values()],
        corridors=[c.to_model() for c in analysis.corridors],
        usable_area=[poly_pts(p) for p in pieces_of(analysis.usable_area)],
        focal_wall_index=analysis.focal_wall_index,
        zones=[z.to_model() for z in zones],
        notices=analysis.notices,
    )


def clear_cache() -> None:
    _cache.clear()
