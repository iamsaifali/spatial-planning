from pydantic import Field

from spatial_planning.models.geometry import PlacedItem, Pose, Room, StrictModel
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import Product
from spatial_planning.models.recommend import Slot
from spatial_planning.models.validation import Finding

MAX_PLACED_ITEMS = 60


# --- "Assist with AI": whole-room deterministic auto-layout -----------------------
# Geometry is decided entirely by the spatial + recommendation engine; no LLM or
# image model is involved in choosing coordinates. See services/recommend/orchestrator.py.


class AssistLayoutRequest(StrictModel):
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    preferences: Preferences = Field(default_factory=Preferences)
    # Optional explicit category order. When None, the sequence is derived from
    # room_type (see services/guide/flow.py::sequence_for_room_type).
    categories: list[str] | None = None
    # Room type: "living_room" (default) or "bedroom"; unknown values fall back to
    # the living-room flow.
    room_type: str | None = "living_room"


class AssistPlacement(StrictModel):
    instance_id: str
    product_id: str
    product: Product  # full product so the canvas can render the ghost + price it
    category: str
    pose: Pose
    zone_id: str | None = None
    slot: Slot = "best_match"
    fit_facts: dict[str, float | str | bool] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    rationale: str = ""  # template copy built from machine-checked facts, never an LLM
    notices: list[str] = Field(default_factory=list)


class AssistSkip(StrictModel):
    category: str
    reason: str  # NO_FIT / ALREADY_PRESENT / a Finding code (e.g. BLOCKS_DOOR_SWING)


class AssistTotals(StrictModel):
    item_count: int
    total_price: int  # BASE_CURRENCY
    currency: str


class AssistLayoutResponse(StrictModel):
    proposal_id: str
    placements: list[AssistPlacement] = Field(default_factory=list)
    skipped: list[AssistSkip] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)  # advisory warnings on the proposed set
    totals: AssistTotals


class AssistTemplate(StrictModel):
    """One complete, selectable layout option (e.g. 'Bed under the window')."""

    label: str  # human name by where the primary piece sits
    recommended: bool  # the best-scoring option, pre-selected in the UI
    layout: AssistLayoutResponse


class AssistLayoutOptions(StrictModel):
    """The set of layout templates returned by /assist/layout - always >= 1."""

    templates: list[AssistTemplate] = Field(default_factory=list)


class HealthResponse(StrictModel):
    status: str
    version: str
    llm_enabled: bool
    render_enabled: bool
