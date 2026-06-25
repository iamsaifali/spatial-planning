from typing import Literal

from pydantic import Field

from app.models.geometry import StrictModel
from app.models.products import Formality, LuxuryTier, Region, RoomType, StyleTag


class Preferences(StrictModel):
    styles: list[StyleTag] = Field(default_factory=list)
    budget_tier: Literal["budget", "mid", "premium"] | None = None
    # whole-room budget in the backend's BASE_CURRENCY (USD)
    total_budget: int | None = Field(default=None, ge=100, le=200_000)
    colors: list[str] = Field(default_factory=list, max_length=8)
    room_purpose: Literal["family", "entertaining", "compact_living", "work_lounge"] | None = None

    # --- foundational cultural / room-type aware fields (all optional, additive) ------
    # Not consumed by scoring yet; present so the API + AI preference layer can start
    # capturing intent ahead of Majlis support. See the recommendation architecture
    # review for how these will feed filtering and scoring later.
    # TODO(majlis): wire room_type into the auto-planner sequence + a perimeter zone
    # generator; wire seating_capacity/luxury_tier/formality into scoring.py.
    room_type: RoomType | None = None
    region: Region | None = None
    seating_capacity: int | None = Field(default=None, ge=1, le=20)
    formality: Formality | None = None
    luxury_tier: LuxuryTier | None = None
    materials: list[str] = Field(default_factory=list, max_length=8)
