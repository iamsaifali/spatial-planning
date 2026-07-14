"""The guided room-building sequence (living-room MVP)."""

from dataclasses import dataclass

from spatial_planning.errors import UNKNOWN_STEP, AppError
from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.products import Product
from spatial_planning.models.recommend import StepInfo


@dataclass(frozen=True)
class Step:
    key: str
    category: str
    title: str
    order: int


STEPS: list[Step] = [
    Step("sofa", "sofa", "Add a Sofa", 1),
    Step("tv_unit", "tv_unit", "Place the TV Unit", 2),
    Step("rug", "rug", "Define with a Rug", 3),
    Step("coffee_table", "coffee_table", "Add a Coffee Table", 4),
    Step("side_table", "side_table", "Add Side Tables", 5),
    Step("accent_chair", "accent_chair", "Add an Accent Chair", 6),
    Step("lighting", "lighting", "Layer in Lighting", 7),
    Step("storage", "storage", "Add Storage", 8),
    Step("decor", "decor", "Finish with Decor", 9),
]

STEP_BY_KEY = {s.key: s for s in STEPS}

ESSENTIAL_WEIGHTS = {
    "sofa": 25,
    "tv_unit": 15,
    "rug": 15,
    "coffee_table": 15,
    "lighting": 10,
    "side_table": 5,
    "accent_chair": 5,
    "storage": 5,
    "decor": 5,
}

ESSENTIAL_REASONS = {
    "sofa": "Every living room needs its main seating anchor.",
    "tv_unit": "A focal media wall gives the seating a direction.",
    "rug": "A rug visually ties the seating zone together.",
    "coffee_table": "A surface within reach makes the seating usable.",
    "lighting": "Layered light makes the room usable in the evening.",
}


# --- room-type step sequences (extension point) ---------------------------------
# The "Assist with AI" orchestrator (services/recommend/orchestrator.py) asks for an
# ordered category sequence by room_type, so room types plug in without touching the
# orchestrator loop.
LIVING_ROOM_SEQUENCE: list[str] = [s.category for s in STEPS]

STEP_SEQUENCES: dict[str, list[str]] = {
    "living_room": LIVING_ROOM_SEQUENCE,
}


def sequence_for_room_type(room_type: str | None) -> list[str]:
    """Ordered category sequence the auto-planner walks for a given room type.

    Unknown / None room types fall back to the living-room sequence so new
    front-end values never 500 the endpoint.
    """
    if room_type is None:
        return LIVING_ROOM_SEQUENCE
    return STEP_SEQUENCES.get(room_type, LIVING_ROOM_SEQUENCE)


def require_step(key: str) -> Step:
    step = STEP_BY_KEY.get(key)
    if step is None:
        raise AppError(code=UNKNOWN_STEP, message=f"Unknown guide step '{key}'.", status_code=404)
    return step


def steps_with_status(placed: list[tuple[PlacedItem, Product]]) -> list[StepInfo]:
    placed_categories = {product.category for _item, product in placed}
    infos: list[StepInfo] = []
    current_assigned = False
    for step in STEPS:
        if step.category in placed_categories:
            status = "done"
        elif not current_assigned:
            status = "current"
            current_assigned = True
        else:
            status = "pending"
        infos.append(
            StepInfo(key=step.key, category=step.category, title=step.title, order=step.order, status=status)
        )
    return infos


def completeness_pct(placed: list[tuple[PlacedItem, Product]]) -> int:
    placed_categories = {product.category for _item, product in placed}
    total = sum(ESSENTIAL_WEIGHTS.values())
    got = sum(w for cat, w in ESSENTIAL_WEIGHTS.items() if cat in placed_categories)
    return round(100 * got / total)


def missing_essentials(placed: list[tuple[PlacedItem, Product]]) -> list[tuple[str, str]]:
    placed_categories = {product.category for _item, product in placed}
    return [
        (cat, ESSENTIAL_REASONS[cat])
        for cat in ("sofa", "tv_unit", "rug", "coffee_table", "lighting")
        if cat not in placed_categories
    ]
