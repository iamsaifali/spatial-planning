"""Real, named zone-strategy implementations.

Each strategy maps role context (category + params + room state) to candidate zones by
calling the SPECIFIC geometry generators in zones.py directly. This replaces the recipe
path's previous reliance on the monolithic room_type/category dispatch
(zones_for_category): the strategy NAME now carries the room-type-specific choice
(focal_wall vs perimeter_walls; front_of_anchor vs center_area), so zones are produced
WITHOUT a room_type switch.

Behavior is byte-equivalent to zones_for_category for the (strategy, category) pairs the
living_room and majlis recipes use (proven by tests). For any pair a recipe does not
currently use, the handler falls back to the legacy dispatch as a safety net (never hit
by the shipped recipes).

The generators remain private to zones.py and are reused as-is - this module is the
public strategy surface over them. zones_for_category and the legacy planner are left
intact for equivalence comparison.
"""

from collections.abc import Callable
from typing import Any

from app.services.spatial.core import RoomAnalysis, ZoneData
from app.services.spatial.zones import (
    CategoryStats,
    PlacedProduct,
    _accent_chair_zones,
    _bed_zones,
    _bedside_zones,
    _coffee_table_zones,
    _decor_zones,
    _free_zone_center,
    _lighting_zones,
    _majlis_sofa_zones,
    _rug_zones,
    _side_table_zones,
    _sofa_zones,
    _storage_zones,
    _tv_zones,
    zones_for_category,
)

ZoneStrategyFn = Callable[
    [str, str, RoomAnalysis, list[PlacedProduct], CategoryStats, dict[str, Any]],
    list[ZoneData],
]


def _fallback(
    category: str, room_type: str, analysis: RoomAnalysis,
    placed: list[PlacedProduct], stats: CategoryStats, params: dict[str, Any],
) -> list[ZoneData]:
    """Safety net for (strategy, category) pairs the shipped recipes don't use:
    reproduce the legacy dispatch exactly. Never reached by living_room / majlis."""
    return zones_for_category(category, analysis, placed, stats, room_type=room_type)


def focal_wall(category, room_type, analysis, placed, stats, params):
    """A large piece against the focal wall (living-room sofa, bedroom bed - headboard
    to the wall)."""
    if category == "sofa":
        return _sofa_zones(analysis, placed, stats)
    if category == "bed":
        return _bed_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def opposite_anchor(category, room_type, analysis, placed, stats, params):
    """Media wall opposite the seating (living-room TV unit)."""
    if category == "tv_unit":
        return _tv_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def front_of_anchor(category, room_type, analysis, placed, stats, params):
    """A frame in front of the seating (living-room rug / coffee table)."""
    if category == "rug":
        return _rug_zones(analysis, placed, stats)
    if category == "coffee_table":
        return _coffee_table_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def beside_anchor(category, room_type, analysis, placed, stats, params):
    """Flanking an anchor (side tables beside a sofa; nightstands beside a bed; majlis
    poufs / floor cushions).

    CONSUMES `anchor_category`: when "bed", side tables anchor to the bed (bedroom
    nightstands); otherwise they anchor to the sofa (living/majlis - the default).
    """
    if category == "side_table":
        if params.get("anchor_category") == "bed":
            return _bedside_zones(analysis, placed, stats)
        return _side_table_zones(analysis, placed, stats)
    if category == "accent_chair":
        return _accent_chair_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def around_anchor(category, room_type, analysis, placed, stats, params):
    """Conversation seating arranged around the sofa (living-room accent chair)."""
    if category == "accent_chair":
        return _accent_chair_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def corners(category, room_type, analysis, placed, stats, params):
    """Corner / surface spots near the seating (lighting, decor).

    params: near, max - documented; not yet consumed (the wrapped generators already
    target corners near the sofa and cap their counts at 3-4).
    """
    if category == "lighting":
        return _lighting_zones(analysis, placed, stats)
    if category == "decor":
        return _decor_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def remaining_wall(category, room_type, analysis, placed, stats, params):
    """A solid wall segment not used by other roles (storage / console)."""
    if category == "storage":
        return _storage_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def perimeter_walls(category, room_type, analysis, placed, stats, params):
    """Inward-facing seating along each clear wall, longest-first (majlis benches).

    params: face="inward" (only inward is supported; reflected in the generator),
    min_wall_cm (currently reflected as the generator's 140cm primary threshold; not yet
    parameterized) - documented, not consumed.
    """
    if category == "sofa":
        return _majlis_sofa_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def center_area(category, room_type, analysis, placed, stats, params):
    """A centred free zone (majlis rug / low table).

    CONSUMES params size_w / size_d when provided. When absent, sizes from the
    category's footprint - rug from the catalog's max dims, other categories from a
    140x120 default - exactly reproducing the legacy majlis zones.
    """
    cat_stats = stats.get(category, {})
    if category == "rug":
        default_w, default_d = cat_stats.get("max_w", 300.0), cat_stats.get("max_d", 240.0)
    else:
        default_w, default_d = 140.0, 120.0
    size_w = float(params.get("size_w", default_w))
    size_d = float(params.get("size_d", default_d))
    return _free_zone_center(analysis, category, size_w, size_d)


def wall_band(category, room_type, analysis, placed, stats, params):
    """Generic band against any clear wall. Not used by the shipped recipes yet;
    delegates to the legacy dispatch until a recipe needs it."""
    return _fallback(category, room_type, analysis, placed, stats, params)


SPATIAL_STRATEGIES: dict[str, ZoneStrategyFn] = {
    "focal_wall": focal_wall,
    "opposite_anchor": opposite_anchor,
    "front_of_anchor": front_of_anchor,
    "beside_anchor": beside_anchor,
    "around_anchor": around_anchor,
    "corners": corners,
    "remaining_wall": remaining_wall,
    "perimeter_walls": perimeter_walls,
    "center_area": center_area,
    "wall_band": wall_band,
}
