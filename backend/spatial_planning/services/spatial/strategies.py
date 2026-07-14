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

from spatial_planning.models.products import placement_group
from spatial_planning.services.spatial.core import RoomAnalysis, ZoneData
from spatial_planning.services.spatial.zones import (
    CategoryStats,
    PlacedProduct,
    _accent_chair_zones,
    _bed_zones,
    _bedside_zones,
    _coffee_table_zones,
    _decor_zones,
    _free_zone_center,
    _l_return_sofa_zones,
    _lamp_on_table_zones,
    _lighting_zones,
    _vases_on_console_zones,
    _reading_chair_zones,
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


def l_return(category, room_type, analysis, placed, stats, params):
    """A perpendicular RETURN sofa forming an L with the primary (big living rooms). The
    generator self-limits: it yields a zone only when the primary is the sole sofa AND the
    return genuinely fits, so small rooms get nothing and only ONE return is ever added."""
    if category == "sofa":
        return _l_return_sofa_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def around_anchor(category, room_type, analysis, placed, stats, params):
    """Conversation seating arranged around the sofa (living-room accent chair).

    The accent chair is the companion for a 2-SEATER primary only. It is skipped when (a) a second
    sofa already formed an L (the L-return IS the companion seating - never both), OR (b) the primary
    is a 3-SEATER: a big sofa pairs with an L-return, never a lone chair (that combo reads as
    unbalanced). So if a 3-seater's L-return didn't fit the room shape it stays a clean single sofa
    rather than sprouting a mismatched chair."""
    if category == "accent_chair":
        sofas = [p for _i, p in placed if placement_group(p.category) == "sofa"]
        if len(sofas) >= 2 or any(p.category == "3-seater-sofa" for p in sofas):
            return []
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
        return _storage_zones(analysis, placed, stats, room_type=room_type)
    return _fallback(category, room_type, analysis, placed, stats, params)


def reading_corner(category, room_type, analysis, placed, stats, params):
    """A reading chair tucked into the empty, door-free corner OPPOSITE the bed (bedroom)."""
    if category == "accent_chair":
        return _reading_chair_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def on_surface(category, room_type, analysis, placed, stats, params):
    """A small item resting ON a placed surface - a table lamp on a nightstand. Yields a zone
    only once its host (a side table) exists, so it depends on the bedside role running first."""
    if category == "lighting":
        return _lamp_on_table_zones(analysis, placed, stats)
    if category == "decor":
        return _vases_on_console_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def center_area(category, room_type, analysis, placed, stats, params):
    """A centred free zone (a room-centred rug / low table).

    CONSUMES params size_w / size_d when provided. When absent, sizes from the
    category's footprint - rug from the catalog's max dims, other categories from a
    140x120 default.
    """
    cat_stats = stats.get(category, {})
    if category == "rug":
        if room_type == "bedroom":
            # A bedroom rug is sized to the ROOM (leaving a comfortable border), not floor-filling
            # like a majlis rug: request ~62% of the room so a small room gets a smaller carpet.
            minx, miny, maxx, maxy = analysis.polygon.bounds
            default_w, default_d = (maxx - minx) * 0.62, (maxy - miny) * 0.62
        else:
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
    "l_return": l_return,
    "around_anchor": around_anchor,
    "corners": corners,
    "remaining_wall": remaining_wall,
    "reading_corner": reading_corner,
    "on_surface": on_surface,
    "center_area": center_area,
    "wall_band": wall_band,
}
