"""Single source of truth for the living-room "Assist with AI" piece checklist.

This is PURE DATA + PURE FUNCTIONS. Nothing here is consumed by the planner yet
(gating / seating / placement wiring is Phase 1+). It exists so the checklist keys,
tiers, recipe-role mapping, and drop-priority ranks live in exactly one place.

See CLAUDE.md §5 for the tier model and the drop-priority ordering:

    Core      (always placed, NOT in the checklist; driven by seating questions):
              sofa (primary/secondary seating), accent_chair (companion seating).
    Essential (in the checklist, pre-checked, can be unchecked):
              rug, coffee_table, tv_unit, floor_lamp.
    Optional  (in the checklist, opt-in):
              chaise_lounge, dining_set*, side_table, console, plant, vases.
              (* dining_set has no recipe role yet.)

Drop priority (keep-longest -> drop-first), rank 1..11:
    sofa(1) -> rug(2) -> coffee_table(3) -> tv_unit(4) -> floor_lamp(5)
    -> chaise_lounge(6) -> dining_set(7) -> side_table(8) -> console(9)
    -> plant(10) -> vases(11)

Core companion seating (accent_chair) shares the top keep-priority with the sofa:
both are core seating, always placed and never dropped, so neither takes a numbered
checklist drop slot — accent_chair mirrors the sofa's rank (1) here.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

Tier = Literal["core", "essential", "optional"]


@dataclass(frozen=True)
class Piece:
    """One furniture piece in the tier/priority model. Immutable, pure data."""

    key: str  # stable string used in Preferences.included_pieces (checklist pieces only)
    label: str  # human-readable name for the UI / notices
    tier: Tier  # "core" | "essential" | "optional"
    role: str | None  # recipe role name, or None for pieces with no role until Phase 3
    store_category: str  # reference store category (see products.ROOM_CATEGORY_PREFERENCE)
    priority: int  # drop-priority rank (1 = keep longest, 11 = drop first)
    extra_roles: tuple[str, ...] = ()  # additional recipe roles this ONE piece gates as a group
    # (e.g. the dining_set gates BOTH the dining table role AND the dining chairs role, so opting
    # the piece in/out toggles the whole group — see piece_for_role / active_roles gating).


# --- The full piece table, keyed by piece key. ORDER = drop-priority order. ----------
# Core pieces (sofa, accent_chair) are recorded for a complete priority table but are
# NOT valid Preferences.included_pieces entries (they are always placed).
_PIECES: tuple[Piece, ...] = (
    # Core seating — always placed, never in the checklist.
    Piece("sofa", "Sofa", "core", "primary_seating", "3-seater-sofa", 1),
    Piece("accent_chair", "Accent chair", "core", "companion_seating", "chair", 1),
    # Essential checklist pieces — pre-checked, can be unchecked.
    Piece("rug", "Rug", "essential", "floor_anchor", "carpet", 2),
    Piece("coffee_table", "Coffee table", "essential", "focal_surface", "center-table", 3),
    Piece("tv_unit", "TV unit", "essential", "focal_media", "tv-table", 4),
    Piece("floor_lamp", "Floor lamp", "essential", "ambient_light", "floor-stand", 5),
    # Optional checklist pieces — opt-in.
    Piece("chaise_lounge", "Chaise lounge", "optional", "lounge_chaise", "chaise-lounge", 6),
    # dining_set is ONE opt-in checklist piece that gates a whole GROUP: the dining table
    # (role "dining_table") plus the ring of dining chairs (role "dining_seating", an extra_role).
    # Both roles map back to this one key, so opting in/out toggles table + chairs together.
    Piece("dining_set", "Dining set", "optional", "dining_table", "dining-table", 7,
          extra_roles=("dining_seating",)),
    Piece("side_table", "Side table", "optional", "support_surface", "service-table", 8),
    Piece("console", "Console", "optional", "storage", "console", 9),
    Piece("plant", "Plant", "optional", "accent", "flower-pot-and-plant", 10),
    Piece("vases", "Vases", "optional", "console_accent", "vase", 11),
)

# Public immutable lookups.
PIECES: Mapping[str, Piece] = MappingProxyType({p.key: p for p in _PIECES})

# Checklist keys, in drop-priority order (the valid Preferences.included_pieces entries).
_CHECKLIST: tuple[str, ...] = tuple(p.key for p in _PIECES if p.tier != "core")


# --- Bedroom piece table (maps the bedroom recipe roles -> checklist keys) ------------
# Same tier model as the living room: core (bed, always placed, never in the checklist),
# essential (pre-checked), optional (opt-in). Keys are room-scoped, so "rug" here maps to
# the bedroom's floor_anchor role independently of the living-room "rug".
_BEDROOM_PIECES: tuple[Piece, ...] = (
    Piece("bed", "Bed", "core", "primary_sleeping", "bed", 1),
    Piece("nightstands", "Nightstands", "essential", "bedside_support", "side-table", 2),
    Piece("wardrobe", "Wardrobe", "essential", "clothing_storage", "wardrobe", 3),
    Piece("rug", "Rug", "essential", "floor_anchor", "carpet", 4),
    Piece("bedside_lamp", "Bedside lamp", "essential", "bedside_lamp", "lampshade", 5),
    # The dressing table comes WITH its stool: the piece gates the vanity + its chair (`vanity_seat`, an
    # extra_role), so opting in the dressing table places both (the chair drops if it can't sit clear).
    Piece("dressing_table", "Dressing table", "optional", "vanity", "dressing-table", 6,
          extra_roles=("vanity_seat",)),
    Piece("reading_chair", "Reading chair", "optional", "reading_nook", "chair", 7),
    # The work nook is ONE opt-in piece gating a GROUP: the desk (role "work_nook") + its office
    # chair (role "work_seat", an extra_role), so opting in/out toggles the desk + chair together.
    Piece("work_nook", "Work nook", "optional", "work_nook", "office-table", 8,
          extra_roles=("work_seat",)),
    Piece("tv_unit", "TV unit", "optional", "media", "tv-table", 9),
    Piece("floor_lamp", "Floor lamp", "optional", "floor_light", "floor-stand", 10),
    Piece("plant", "Plant", "optional", "accent", "flower-pot-and-plant", 11),
    # Opt-in sitting area: a compact LOUNGE sofa (best-fit from sofa / 2-/3-seater) on a clear wall +
    # its CENTRE table in front. Distinct keys (not "sofa"/"coffee_table") so they never collide with
    # the living-room core pieces in the global priority table. The centre table needs the sofa. The sofa
    # piece ALSO gates a floor-stand beside it (`lounge_light`, an extra_role) - it comes with the sofa.
    Piece("lounge_sofa", "Sofa", "optional", "lounge_sofa", "2-seater-sofa", 12,
          extra_roles=("lounge_light",)),
    Piece("center_table", "Center table", "optional", "lounge_center", "center-table", 13),
)

# Per-room piece tables. A room type ABSENT from this registry is NOT gated (its recipe
# runs unchanged) - preserving every other room type's behaviour.
_ROOM_PIECES: Mapping[str, tuple[Piece, ...]] = MappingProxyType(
    {"living_room": _PIECES, "bedroom": _BEDROOM_PIECES}
)


# Reverse role -> piece (first piece declared for a role wins; None roles are skipped).
# A piece may own SEVERAL roles (its primary `role` plus any `extra_roles`); every one of them
# maps back to the same piece, so a multi-role group (dining table + chairs) is gated by one key.
def _build_by_role(pcs: tuple[Piece, ...]) -> Mapping[str, Piece]:
    mapping: dict[str, Piece] = {}
    for p in reversed(pcs):
        for r in (p.role, *p.extra_roles):
            if r is not None:
                mapping[r] = p
    return MappingProxyType(mapping)


# Per-room role->piece maps, built once. Living-room stays available as `_BY_ROLE` for
# back-compat with any caller that doesn't pass a room type.
_BY_ROLE_BY_ROOM: Mapping[str, Mapping[str, Piece]] = MappingProxyType(
    {rt: _build_by_role(pcs) for rt, pcs in _ROOM_PIECES.items()}
)
_BY_ROLE: Mapping[str, Piece] = _BY_ROLE_BY_ROOM["living_room"]


def _pieces_for_room(room_type: str) -> tuple[Piece, ...]:
    return _ROOM_PIECES.get(room_type, ())


def checklist_keys(room_type: str = "living_room") -> tuple[str, ...]:
    """The canonical checklist keys for a room, in drop-priority order (core excluded)."""
    return tuple(p.key for p in _pieces_for_room(room_type) if p.tier != "core")


def essential_keys(room_type: str = "living_room") -> tuple[str, ...]:
    """The pre-checked essential checklist keys for a room."""
    return tuple(p.key for p in _pieces_for_room(room_type) if p.tier == "essential")


def resolve_active_pieces(included: list[str] | None, room_type: str = "living_room") -> frozenset[str]:
    """The set of checklist piece keys the planner should place, scoped to a room type.

    `None` -> the essentials-only default (the pre-checked pieces). A list -> exactly
    those entries, intersected with the room's valid checklist keys (unknown/core keys
    ignored — core is always placed, never gated). A room with no piece table -> empty
    set (its recipe runs ungated; the caller returns all roles). Pure function.
    """
    if room_type not in _ROOM_PIECES:
        return frozenset()
    if included is None:
        return frozenset(essential_keys(room_type))
    valid = set(checklist_keys(room_type))
    return frozenset(k for k in included if k in valid)


def piece(key: str, room_type: str = "living_room") -> Piece | None:
    """The Piece for a checklist/core key in a room, or None if unknown."""
    for p in _pieces_for_room(room_type):
        if p.key == key:
            return p
    return None


def piece_for_role(role: str, room_type: str = "living_room") -> Piece | None:
    """The Piece mapped to a recipe role name for a room, or None if no piece owns it."""
    return _BY_ROLE_BY_ROOM.get(room_type, _BY_ROLE).get(role)


def priority_of(key: str) -> int | None:
    """Drop-priority rank for a piece key (1 = keep longest), or None if unknown."""
    p = PIECES.get(key)
    return p.priority if p is not None else None


def is_essential(key: str) -> bool:
    """True if the key is an essential (pre-checked) checklist piece."""
    p = PIECES.get(key)
    return p is not None and p.tier == "essential"
