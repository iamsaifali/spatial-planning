from typing import Literal

from pydantic import Field

from app.models.geometry import Point, Pose, StrictModel

Severity = Literal["error", "warning", "info"]

# Finding codes
OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
OVERLAP_ITEM = "OVERLAP_ITEM"
BLOCKS_DOOR_SWING = "BLOCKS_DOOR_SWING"
BLOCKS_WALKWAY = "BLOCKS_WALKWAY"
NARROWS_WALKWAY = "NARROWS_WALKWAY"
BLOCKS_WINDOW = "BLOCKS_WINDOW"
CLEARANCE_TOO_TIGHT = "CLEARANCE_TOO_TIGHT"
CLEARANCE_TOO_FAR = "CLEARANCE_TOO_FAR"
TV_TOO_CLOSE = "TV_TOO_CLOSE"
FRONT_BLOCKED = "FRONT_BLOCKED"
TV_VIEW_BLOCKED = "TV_VIEW_BLOCKED"  # a tall item sits in the TV->sofa sightline
DOMINATES_ROOM = "DOMINATES_ROOM"

ERROR_CODES = {OUT_OF_BOUNDS, OVERLAP_ITEM, BLOCKS_DOOR_SWING}
MUST_FIX_CODES = ERROR_CODES | {BLOCKS_WALKWAY}


class Finding(StrictModel):
    code: str
    severity: Severity
    message: str
    item_instance_id: str | None = None
    other_instance_id: str | None = None
    geometry: list[Point] | None = None


class AutoFix(StrictModel):
    pose: Pose
    resolves: list[str] = Field(default_factory=list)


class BetterPlacement(StrictModel):
    pose: Pose
    zone_id: str | None = None


class ValidateResponse(StrictModel):
    findings: list[Finding]
    autofix: AutoFix | None = None
    better_placement: BetterPlacement | None = None


class SuggestResponse(StrictModel):
    pose: Pose
    zone_id: str | None = None
    alternatives: list[Pose] = Field(default_factory=list)
