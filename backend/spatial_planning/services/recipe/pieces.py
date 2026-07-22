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

# Reverse role -> piece (first piece declared for a role wins; None roles are skipped).
# A piece may own SEVERAL roles (its primary `role` plus any `extra_roles`); every one of them
# maps back to the same piece, so a multi-role group (dining table + chairs) is gated by one key.
def _build_by_role() -> Mapping[str, Piece]:
    mapping: dict[str, Piece] = {}
    for p in reversed(_PIECES):
        for r in (p.role, *p.extra_roles):
            if r is not None:
                mapping[r] = p
    return MappingProxyType(mapping)


_BY_ROLE: Mapping[str, Piece] = _build_by_role()


def checklist_keys() -> tuple[str, ...]:
    """The canonical checklist keys, in drop-priority order (core pieces excluded)."""
    return _CHECKLIST


def essential_keys() -> tuple[str, ...]:
    """The pre-checked essential checklist keys (rug, coffee_table, tv_unit, floor_lamp)."""
    return tuple(p.key for p in _PIECES if p.tier == "essential")


def resolve_active_pieces(included: list[str] | None) -> frozenset[str]:
    """The set of checklist piece keys the planner should place.

    `None` -> the essentials-only default (the pre-checked pieces). A list -> exactly
    those entries, intersected with the valid checklist keys (unknown keys ignored,
    core keys like 'sofa' ignored — core is always placed, never gated). Pure function.
    """
    if included is None:
        return frozenset(essential_keys())
    valid = set(_CHECKLIST)
    return frozenset(k for k in included if k in valid)


def piece(key: str) -> Piece | None:
    """The Piece for a checklist/core key, or None if unknown."""
    return PIECES.get(key)


def piece_for_role(role: str) -> Piece | None:
    """The Piece mapped to a recipe role name, or None if no piece owns that role."""
    return _BY_ROLE.get(role)


def priority_of(key: str) -> int | None:
    """Drop-priority rank for a piece key (1 = keep longest), or None if unknown."""
    p = PIECES.get(key)
    return p.priority if p is not None else None


def is_essential(key: str) -> bool:
    """True if the key is an essential (pre-checked) checklist piece."""
    p = PIECES.get(key)
    return p is not None and p.tier == "essential"
