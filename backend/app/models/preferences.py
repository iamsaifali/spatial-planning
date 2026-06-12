from typing import Literal

from pydantic import Field

from app.models.geometry import StrictModel
from app.models.products import StyleTag


class Preferences(StrictModel):
    styles: list[StyleTag] = Field(default_factory=list)
    budget_tier: Literal["budget", "mid", "premium"] | None = None
    # whole-room budget in the backend's BASE_CURRENCY (USD)
    total_budget: int | None = Field(default=None, ge=100, le=200_000)
    colors: list[str] = Field(default_factory=list, max_length=8)
    room_purpose: Literal["family", "entertaining", "compact_living", "work_lounge"] | None = None
