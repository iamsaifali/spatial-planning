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
    # Top-level engine selector. "living_room" (default) keeps the existing family
    # placement engine; "majlis" routes to the perimeter-seating Majlis engine. Kept
    # separate from room_purpose, which is a sub-flavour of the living-room engine.
    room_type: Literal["living_room", "majlis"] = "living_room"
    room_purpose: Literal["family", "entertaining", "compact_living", "work_lounge"] | None = None
    # how many people the seating should comfortably hold; drives the layout plan.
    # Ignored for room_type="majlis" (perimeter seating fills the walls automatically).
    seating_capacity: int | None = Field(default=None, ge=1, le=12)
