from typing import Literal

from pydantic import Field

from app.models.analysis import Zone
from app.models.geometry import Pose, StrictModel
from app.models.products import Product

CopySource = Literal["llm", "template", "offline"]

Slot = Literal["best_match", "budget", "premium"]

# Recommendation notices
NOTICE_OVER_BUDGET = "OVER_BUDGET"
NOTICE_UNDER_BUDGET = "UNDER_BUDGET"
NOTICE_PREORDER = "PREORDER"
NOTICE_TIGHT_FIT = "TIGHT_FIT"
NOTICE_NO_FIT = "NO_FIT"
NOTICE_ROOM_CHANGED = "ROOM_CHANGED"


class WhyItFits(StrictModel):
    why_product: str
    why_size: str
    why_placement: str
    copy_source: CopySource = "template"


class Recommendation(StrictModel):
    slot: Slot
    product: Product
    why_it_fits: WhyItFits
    suggested_pose: Pose
    zone_id: str | None = None
    fit_facts: dict[str, float | str | bool] = Field(default_factory=dict)
    notices: list[str] = Field(default_factory=list)


class EmptySlot(StrictModel):
    slot: Slot
    reason: str  # NO_FIT etc.
    hints: dict[str, float | str] = Field(default_factory=dict)


class Guidance(StrictModel):
    message: str
    tip: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    copy_source: CopySource = "template"


class StepInfo(StrictModel):
    key: str
    category: str
    title: str
    order: int
    status: Literal["done", "current", "pending"] = "pending"


class StepsResponse(StrictModel):
    steps: list[StepInfo]


class StepResponse(StrictModel):
    analysis_hash: str
    step_key: str
    guidance: Guidance
    zones: list[Zone]
    recommendations: list[Recommendation] = Field(default_factory=list)
    empty_slots: list[EmptySlot] = Field(default_factory=list)
