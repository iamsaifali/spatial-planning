"""Predicate reference layer — a MAPPING, not an engine.

Recipes reference predicates by name; this module resolves each name to a descriptor
that points at the EXISTING validation vocabulary (the Finding codes in
app.models.validation). It moves no validation logic and builds no predicate engine —
the deterministic gate (validate_item) remains the sole, unchanged authority.

Predicate kinds:
  * "hard"      - enforced by the gate as a MUST_FIX error (links to a Finding code)
  * "soft"      - surfaced by the gate as a warning (links to a Finding code)
  * "strategic" - achieved by the zone strategy itself, not validated (e.g. against_wall)
  * "goal"      - a room-level intent honoured by strategy + count guards (e.g. keep_center_open)
"""

from dataclasses import dataclass

from app.models.validation import (
    BLOCKS_DOOR_SWING,
    BLOCKS_WALKWAY,
    BLOCKS_WINDOW,
    CLEARANCE_TOO_TIGHT,
    OUT_OF_BOUNDS,
    OVERLAP_ITEM,
)


@dataclass(frozen=True)
class Predicate:
    name: str
    kind: str  # "hard" | "soft" | "strategic" | "goal"
    finding_code: str | None = None  # the Finding the gate raises, for hard/soft kinds


PREDICATE_REGISTRY: dict[str, Predicate] = {
    # hard — these are exactly the gate's error-level checks
    "in_bounds": Predicate("in_bounds", "hard", OUT_OF_BOUNDS),
    "no_overlap": Predicate("no_overlap", "hard", OVERLAP_ITEM),
    "not_block_door": Predicate("not_block_door", "hard", BLOCKS_DOOR_SWING),
    "keep_walkway": Predicate("keep_walkway", "hard", BLOCKS_WALKWAY),
    # soft — gate warnings
    "not_block_window": Predicate("not_block_window", "soft", BLOCKS_WINDOW),
    "min_clearance": Predicate("min_clearance", "soft", CLEARANCE_TOO_TIGHT),
    # strategic / goal — honoured by the zone strategy + count guards, not validated
    "against_wall": Predicate("against_wall", "strategic", None),
    "centered": Predicate("centered", "strategic", None),
    "keep_center_open": Predicate("keep_center_open", "goal", None),
}


def resolve_predicate(name: str) -> Predicate:
    predicate = PREDICATE_REGISTRY.get(name)
    if predicate is None:
        raise KeyError(f"Unknown predicate reference '{name}'")
    return predicate
