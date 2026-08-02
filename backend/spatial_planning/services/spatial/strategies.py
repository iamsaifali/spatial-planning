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

from spatial_planning.models.products import seat_target_for_area
from spatial_planning.services.spatial.core import RoomAnalysis, ZoneData
from spatial_planning.services.spatial.geometry_utils import front_vector
from spatial_planning.services.spatial.zones import (
    CategoryStats,
    PlacedProduct,
    _accent_chair_zones,
    _bed_zones,
    _bedroom_rug_zones,
    _bedroom_tv_zones,
    _bedside_zones,
    _chaise_zones,
    _coffee_table_zones,
    _decor_zones,
    _desk_chair_zones,
    _desk_zones,
    _dining_chair_zones,
    _dining_zones,
    _find_placed,
    _free_zone_center,
    _l_return_sofa_zones,
    _lamp_on_table_zones,
    _lounge_light_zones,
    _lounge_sofa_zones,
    _vanity_chair_zones,
    _lighting_zones,
    _nook_rug_zones,
    _nook_satellite_zones,
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
        # Phase 4: when no TV was requested (params tv_requested=False, injected by the
        # orchestrator), relax the window-wall avoidance so the sofa takes the best wall.
        return _sofa_zones(analysis, placed, stats, tv_requested=params.get("tv_requested", True), side_shift_mode=params.get("side_shift_mode"))
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
    """A perpendicular RETURN sofa forming an L (or, on the free flank of an existing return, a U) with
    the primary (big living rooms). The generator self-limits to `MAX_RETURN_SOFAS` and to rooms above
    the area guard, so small rooms get nothing. `return_category` (from params, default 2-seater) sizes
    the return - the secondary-sofa fill loop passes 3-seater vs 2-seater by the remaining seat gap."""
    if category == "sofa":
        return _l_return_sofa_zones(analysis, placed, stats, return_category=params.get("return_category", "2-seater-sofa"))
    return _fallback(category, room_type, analysis, placed, stats, params)


def around_anchor(category, room_type, analysis, placed, stats, params):
    """Conversation seating arranged around the sofa (living-room accent chair).

    Sofa-first ladder (see CLAUDE.md 5.1): accent chairs are the LAST resort - a chair is
    added only to TOP UP the seats the sofa group (primary + L-return) couldn't reach. So we
    offer chair zones only while the seat TARGET is not yet met, and return NONE once the
    placed seating already satisfies it (an L-return / big sofa that seats the room needs no
    chair). This lets an odd +1 top up a 3-seater + L-return (=5) toward a target of 6, while
    a target of 5 that the sofa group already meets sprouts no chair.

    The precise gap (and the user's EXPLICIT seat count) is enforced by the orchestrator's
    gap-driven cap; this area-based target keeps the strategy honest when no count is given
    and never blocks a chair the planner still wants (the placed seating rarely reaches the
    area target from sofas alone)."""
    if category == "accent_chair":
        seated = sum(p.seating_capacity for _i, p in placed if p.seating_capacity > 0)
        if seated >= seat_target_for_area(analysis.area_cm2):
            return []  # the seat target is already met by the sofa group - no chair needed
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
        if room_type == "bedroom":
            # A bedroom plant tucks closer to furniture than a living-room plant beside the sofa
            # group (tighter buffer -> frees a second corner in a large room), and its footprint
            # SCALES WITH THE ROOM so a big bedroom gets a substantial floor plant, not a tiny pot
            # lost in the space (a 60cm zone -> ~45cm pot; a 105cm zone -> a ~80cm planter).
            area_m2 = analysis.area_cm2 / 10_000.0
            size = max(65.0, min(100.0, 65.0 + (area_m2 - 15.0) * 2.3))
            return _decor_zones(analysis, placed, stats, blocker_buffer=18.0, size=size)
        return _decor_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def remaining_wall(category, room_type, analysis, placed, stats, params):
    """A solid wall segment not used by other roles (storage / console)."""
    if category == "storage":
        return _storage_zones(
            analysis, placed, stats, room_type=room_type, allow_small_console=True,
            tv_requested=params.get("tv_requested", True),
            store_category=params.get("store_category"),
        )
    return _fallback(category, room_type, analysis, placed, stats, params)


def reading_corner(category, room_type, analysis, placed, stats, params):
    """A reading chair tucked into the empty, door-free corner OPPOSITE the bed (bedroom)."""
    if category == "accent_chair":
        return _reading_chair_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def work_desk(category, room_type, analysis, placed, stats, params):
    """The bedroom work-nook DESK against a clear wall with room to sit (away from bed / storage)."""
    if category == "desk":
        return _desk_zones(analysis, placed, stats, tv_requested=params.get("tv_requested", True))
    return _fallback(category, room_type, analysis, placed, stats, params)


def bed_media(category, room_type, analysis, placed, stats, params):
    """The bedroom TV unit on the wall the bed faces (opposite the headboard)."""
    if category == "tv_unit":
        return _bedroom_tv_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def desk_seat(category, room_type, analysis, placed, stats, params):
    """The work-nook CHAIR pulled up in front of the placed desk, facing it (reuses the vanity seat)."""
    if category == "accent_chair":
        return _desk_chair_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def vanity_seat(category, room_type, analysis, placed, stats, params):
    """The dressing-table's STOOL: a small chair in front of the vanity, facing it - only where it won't
    block a walkway or crowd the bed. Requires a dressing table; else no stool."""
    if category == "accent_chair":
        return _vanity_chair_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def lounge_seat(category, room_type, analysis, placed, stats, params):
    """The bedroom LOUNGE sofa: a compact sofa hugging a clear wall of its own, facing into the room -
    the seat of a small sitting area (its centre table pulls up in front via `front_of_anchor`)."""
    if category == "sofa":
        return _lounge_sofa_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def lounge_table(category, room_type, analysis, placed, stats, params):
    """The bedroom lounge's CENTRE table, pulled up in front of the lounge sofa. Requires the sofa: no
    lounge sofa placed -> no table (never a marooned room-centred table like the living-room fallback)."""
    if category == "coffee_table":
        if _find_placed(placed, "sofa") is None:
            return []
        return _coffee_table_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def lounge_light(category, room_type, analysis, placed, stats, params):
    """A floor lamp (floor-stand) beside the lounge sofa's arm, completing the sitting area. Requires
    the sofa: no lounge sofa placed -> no lamp."""
    if category == "lighting":
        return _lounge_light_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def chaise(category, room_type, analysis, placed, stats, params):
    """A standalone chaise-lounge placed WALL-HUGGING: back against a clear secondary wall, long
    side parallel, facing into the room. Opt-in; never competes as a primary/secondary sofa
    (its own placement role)."""
    if category == "chaise":
        return _chaise_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def nook_rug(category, room_type, analysis, placed, stats, params):
    """A second SMALL rug anchoring the reading nook under the chaise (massive rooms only, chaise placed)."""
    if category == "rug":
        return _nook_rug_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def nook_satellite(category, room_type, analysis, placed, stats, params):
    """A small accent (floor lamp / side table) beside the chaise, completing the reading-nook vignette
    (massive rooms only, chaise placed)."""
    if category in ("lighting", "side_table"):
        return _nook_satellite_zones(analysis, placed, stats, category)
    return _fallback(category, room_type, analysis, placed, stats, params)


def dining(category, room_type, analysis, placed, stats, params):
    """A dining TABLE in an open pocket BESIDE the conversation group (its own separate area,
    never overlapping the seating). Opt-in; no separate open floor -> no zone -> skipped."""
    if category == "dining_table":
        return _dining_zones(analysis, placed, stats)
    return _fallback(category, room_type, analysis, placed, stats, params)


def dining_ring(category, room_type, analysis, placed, stats, params):
    """Dining chairs ringed around the placed dining table, each facing it. Yields one candidate
    zone per ring position; the per-anchor loop validates + keeps the ones that fit. No table
    placed -> no zones -> no chairs (never orphaned)."""
    if category == "accent_chair":
        return _dining_chair_zones(analysis, placed, stats)
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
            # A big rug anchored at the foot of the bed (only ~1/8 of the bed on it, the rest fanning
            # forward into the room). See `_bedroom_rug_zones` - a near-edge-anchored FRAME zone.
            return _bedroom_rug_zones(analysis, placed, stats)
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
    "work_desk": work_desk,
    "desk_seat": desk_seat,
    "vanity_seat": vanity_seat,
    "lounge_seat": lounge_seat,
    "lounge_table": lounge_table,
    "lounge_light": lounge_light,
    "bed_media": bed_media,
    "chaise": chaise,
    "nook_rug": nook_rug,
    "nook_satellite": nook_satellite,
    "dining": dining,
    "dining_ring": dining_ring,
    "on_surface": on_surface,
    "center_area": center_area,
    "wall_band": wall_band,
}
