from typing import Literal

from pydantic import Field

from app.models.analysis import Zone
from app.models.geometry import Pose, StrictModel
from app.models.products import Product

CopySource = Literal["llm", "template", "offline"]

# Recommendation notices
NOTICE_PREORDER = "PREORDER"
NOTICE_TIGHT_FIT = "TIGHT_FIT"
NOTICE_NO_FIT = "NO_FIT"
NOTICE_SKIPPED_TIGHT = "SKIPPED_TIGHT_SPACE"  # non-essential left out: no clean spot
NOTICE_ROOM_CHANGED = "ROOM_CHANGED"
NOTICE_QUANTITY_RELAXED = "QUANTITY_RELAXED"


class WhyItFits(StrictModel):
    why_product: str
    why_size: str
    why_placement: str
    copy_source: CopySource = "template"


class Recommendation(StrictModel):
    rank: int  # 0 = best style+colour match
    product: Product
    why_it_fits: WhyItFits
    suggested_pose: Pose
    zone_id: str | None = None
    fit_facts: dict[str, float | str | bool] = Field(default_factory=dict)
    notices: list[str] = Field(default_factory=list)


class NoFit(StrictModel):
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
    quantity: int = 1
    placed_count: int = 0


class StepsResponse(StrictModel):
    steps: list[StepInfo]


class StepResponse(StrictModel):
    analysis_hash: str
    step_key: str
    guidance: Guidance
    zones: list[Zone]
    recommendations: list[Recommendation] = Field(default_factory=list)
    no_fit: NoFit | None = None  # set when nothing fits the zone
    quantity: int = 1
