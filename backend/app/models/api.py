from pydantic import Field

from app.models.geometry import PlacedItem, Pose, Room, StrictModel
from app.models.preferences import Preferences
from app.models.products import Product
from app.models.recommend import CopySource
from app.models.validation import Finding

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
