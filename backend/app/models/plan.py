"""Layout-plan contract: the LLM Director's structured output.

The LLM decides ONLY content - which furniture categories belong, how many of
each, a placement priority, and whether each is essential. It never emits
coordinates, products, or arrangement intent; placement is owned entirely by the
deterministic per-category geometric rules in services/spatial.
"""

from typing import Literal

from pydantic import Field

from app.models.geometry import StrictModel
from app.models.products import Category

Tier = Literal["essential", "non_essential"]


class PlanItem(StrictModel):
    category: Category
    # The LLM owns the count (it reasons from room size + purpose). This ceiling is
    # only an anti-garbage bound; archetypes.caps_for does the real area-scaled clamp.
    quantity: int = Field(default=1, ge=1, le=12)
    # essential = must-have; non_essential = include only if the room has space.
    tier: Tier = "essential"
    priority: int = Field(default=5, ge=0, le=99)  # lower = placed earlier (essentials first)
    # open-ended "fill until full": quantity is a soft estimate, not a cap. The user keeps
    # placing this category until the geometry reports no slot (e.g. majlis sofas line the
    # walls regardless of the up-front count). Family steps leave this False.
    fill: bool = False


class LayoutPlan(StrictModel):
    archetype: str = ""
    items: list[PlanItem] = Field(default_factory=list)
    rationale: str = ""
    # set when the requested seating exceeds what the room can hold at proper
    # clearances; the plan is built for what fits and this explains the shortfall.
    seating_note: str | None = None
