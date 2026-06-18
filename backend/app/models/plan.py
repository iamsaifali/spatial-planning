"""Layout-plan contract: the LLM Director's structured output.

The LLM never emits coordinates or products - only a list of PlanItems, each
choosing a furniture category, a quantity, and an ARRANGEMENT INTENT expressed
as a closed-vocabulary anchor. The deterministic resolver turns each anchor into
real poses (see services/plan/resolver.py).
"""

from typing import Literal

from pydantic import Field

from app.models.geometry import StrictModel
from app.models.products import Category

# Closed vocabulary shared by the LLM schema and the deterministic resolver.
Anchor = Literal[
    "on_focal_wall",      # back to the focal wall, facing into the room
    "facing",             # rotate to face anchor_ref's centre
    "flanking",           # mirrored pair either side of anchor_ref
    "in_front_of",        # in front of anchor_ref along its forward axis
    "beside",             # offset along anchor_ref's lateral axis
    "conversation_angle", # splayed toward the seating centre
    "corner",             # tucked into a room corner
    "center",             # floating in the usable-area centre
]
AnchorRef = Literal["sofa", "tv_unit", "window", "focal_wall", "room"]


class PlanItem(StrictModel):
    category: Category
    quantity: int = Field(default=1, ge=1, le=4)
    anchor: Anchor = "center"
    anchor_ref: AnchorRef = "room"
    priority: int = Field(default=5, ge=0, le=99)  # lower = placed earlier
    params: dict[str, float] = Field(default_factory=dict)  # angle/gap/dist overrides


class LayoutPlan(StrictModel):
    archetype: str = ""
    items: list[PlanItem] = Field(default_factory=list)
    rationale: str = ""
