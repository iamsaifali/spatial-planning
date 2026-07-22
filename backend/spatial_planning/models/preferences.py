from typing import Literal

from pydantic import Field, field_validator

from spatial_planning.models.geometry import StrictModel
from spatial_planning.models.products import Formality, LuxuryTier, Region, RoomType, StyleTag
from spatial_planning.models.style_metadata import COLOR_FAMILIES, STYLES


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

    # --- rich style / colour preference (user-selected in the UI; drives metadata FILTERING of the
    # real catalog, alongside the legacy `styles`/`colors` which still feed soft scoring) ---
    # `style`: ONE rich style name from style_metadata.STYLES (e.g. "Modern", "Japandi").
    # `color_families`: one or more palette families from style_metadata.COLOR_FAMILIES
    # (e.g. "Warm Neutral", "Wood/Natural"); products are matched on their `main_family`.
    style: str | None = None
    # up to all 11 COLOR_FAMILIES (the "Pick your style" dialog lets you choose any). color_families is
    # layout-inert - it only narrows product selection ("filter when available") - so a large set never
    # destabilises the layout; it just widens the acceptable colours. Capping below 11 would 422 a valid
    # UI selection and leave the canvas blank.
    color_families: list[str] = Field(default_factory=list, max_length=11)

    # --- living-room "Assist with AI" checklist intent (all optional, additive) --------
    # PHASE 0 CONTRACT ONLY: these are captured but NOT consumed by the planner yet.
    #
    # `included_pieces`: the checklist pieces the user wants placed, as piece keys from
    # services/recipe/pieces.py::checklist_keys() (rug, coffee_table, tv_unit, floor_lamp,
    # chaise_lounge, dining_set, side_table, console, plant, vases). Core pieces
    # (sofa / accent_chair) are ALWAYS placed and are NOT valid entries here. `None` means
    # "use the room default" (essentials only) — Phase 1 resolves that default and gates
    # the recipe on this list; do not resolve it here.
    included_pieces: list[str] | None = None
    # `sofa_type`: the Q2 main-sofa choice. "auto" preserves today's behaviour (the planner
    # picks the sofa size from room area). Phase 2 consumes the explicit choices.
    sofa_type: Literal["auto", "2-seater", "3-seater", "l-shape"] = "auto"

    # INTERNAL (set by the planner, not the UI): force a COMPACT (2-seater) primary sofa + accent chair
    # instead of a 3-seater. The planner re-plans with this on when a 3-seater primary couldn't get its
    # L-return (narrow room / windows on both long walls), so a room never ends up a lone 3-seater.
    compact_seating: bool = False

    @field_validator("style")
    @classmethod
    def _known_style(cls, v: str | None) -> str | None:
        if v is not None and v not in STYLES:
            raise ValueError(f"unknown style {v!r}; expected one of style_metadata.STYLES")
        return v

    @field_validator("color_families")
    @classmethod
    def _known_families(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in COLOR_FAMILIES]
        if unknown:
            raise ValueError(f"unknown colour families {unknown}; expected style_metadata.COLOR_FAMILIES")
        return v
