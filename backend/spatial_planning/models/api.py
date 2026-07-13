from pydantic import Field

from spatial_planning.models.geometry import PlacedItem, Pose, Room, StrictModel
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import Product
from spatial_planning.models.recommend import CopySource, Slot
from spatial_planning.models.validation import Finding

MAX_PLACED_ITEMS = 60


class AnalyzeRequest(StrictModel):
    room: Room


class StepRequest(StrictModel):
    room: Room
    preferences: Preferences = Field(default_factory=Preferences)
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)


class SuggestRequest(StrictModel):
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    product_id: str
    zone_id: str | None = None


class ValidateItemRequest(StrictModel):
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    item: PlacedItem


class SummaryRequest(StrictModel):
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    preferences: Preferences = Field(default_factory=Preferences)
    currency: str | None = None  # used only to phrase narrative copy


class SummaryLine(StrictModel):
    product: Product
    pose: Pose
    instance_id: str
    line_price: int


class MissingEssential(StrictModel):
    category: str
    label: str
    reason: str


class SuggestedUpgrade(StrictModel):
    from_product_id: str
    from_name: str
    to_product: Product
    delta: int
    reason: str


class SummaryNarrative(StrictModel):
    text: str
    copy_source: CopySource = "template"


class SummaryResponse(StrictModel):
    items: list[SummaryLine]
    total_price: int
    by_category: dict[str, int]
    completeness_pct: int
    missing_essentials: list[MissingEssential]
    suggested_upgrades: list[SuggestedUpgrade]
    layout_findings: list[Finding]
    narrative: SummaryNarrative


class RenderRequest(StrictModel):
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    preferences: Preferences = Field(default_factory=Preferences)
    canvas_png_b64: str = Field(min_length=8)
    size: str | None = None


class RenderResponse(StrictModel):
    image_b64: str
    prompt_facts: dict


class AssistantRequest(StrictModel):
    question: str = Field(min_length=1, max_length=600)
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    preferences: Preferences = Field(default_factory=Preferences)
    step_key: str | None = None


class AssistantResponse(StrictModel):
    answer: str
    related_tip: str | None = None
    facts_used: list[str] = Field(default_factory=list)
    copy_source: CopySource = "offline"


# --- "Assist with AI": whole-room deterministic auto-layout -----------------------
# Geometry is decided entirely by the spatial + recommendation engine; no LLM or
# image model is involved in choosing coordinates. See services/recommend/orchestrator.py.


class AssistLayoutRequest(StrictModel):
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    preferences: Preferences = Field(default_factory=Preferences)
    # Optional explicit category order. When None, the sequence is derived from
    # room_type (see app/services/guide/flow.py::sequence_for_room_type).
    categories: list[str] | None = None
    # Extension point for future room types (e.g. "majlis"). Defaults to the
    # living-room flow; unknown values fall back to living-room and never error.
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


class DesignCreateRequest(StrictModel):
    name: str | None = Field(default=None, max_length=120)
    room: Room
    placed_items: list[PlacedItem] = Field(default_factory=list, max_length=MAX_PLACED_ITEMS)
    preferences: Preferences = Field(default_factory=Preferences)


class DesignResponse(StrictModel):
    design_id: str
    name: str
    room: Room
    placed_items: list[PlacedItem]
    preferences: Preferences
    total_price: int
    item_count: int
    created_at: str
    updated_at: str


class DesignSummary(StrictModel):
    design_id: str
    name: str
    item_count: int
    total_price: int
    created_at: str


class DesignCreateResponse(StrictModel):
    design_id: str
    share_path: str


class Contact(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)


class CheckoutItem(StrictModel):
    product_id: str
    qty: int = Field(ge=1, le=20)


class CheckoutRequest(StrictModel):
    design_id: str | None = None
    items: list[CheckoutItem] | None = Field(default=None, max_length=80)
    contact: Contact
    currency: str | None = None  # display currency for the order record


class OrderLine(StrictModel):
    product_id: str
    name: str
    qty: int
    unit_price: int  # BASE_CURRENCY


class OrderResponse(StrictModel):
    order_id: str
    status: str
    total: int  # BASE_CURRENCY
    currency: str
    display_total: int  # total converted to `currency` at order time
    eta_days: int
    lines: list[OrderLine]
    created_at: str


class HealthResponse(StrictModel):
    status: str
    version: str
    llm_enabled: bool
    render_enabled: bool
