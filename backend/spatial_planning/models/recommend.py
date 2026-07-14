from typing import Literal

from spatial_planning.models.geometry import StrictModel

Slot = Literal["best_match", "budget", "premium"]

# Recommendation notices
NOTICE_OVER_BUDGET = "OVER_BUDGET"
NOTICE_UNDER_BUDGET = "UNDER_BUDGET"
NOTICE_PREORDER = "PREORDER"
NOTICE_TIGHT_FIT = "TIGHT_FIT"
NOTICE_NO_FIT = "NO_FIT"
NOTICE_ROOM_CHANGED = "ROOM_CHANGED"


class StepInfo(StrictModel):
    key: str
    category: str
    title: str
    order: int
    status: Literal["done", "current", "pending"] = "pending"
