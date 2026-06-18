"""The guided room-building sequence (living-room MVP)."""

from collections import Counter
from dataclasses import dataclass

from app.errors import UNKNOWN_STEP, AppError
from app.models.geometry import PlacedItem
from app.models.plan import LayoutPlan
from app.models.products import CATEGORY_LABELS, Product
from app.models.recommend import StepInfo


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


def _step_title(category: str) -> str:
    step = STEP_BY_KEY.get(category)
    return step.title if step else f"Add {CATEGORY_LABELS.get(category, category.title())}"


def steps_from_plan(
    plan: LayoutPlan, placed: list[tuple[PlacedItem, Product]]
) -> list[StepInfo]:
    """Dynamic, plan-driven steps with per-category quantity + status.

    A category stays 'current' until its full quantity is placed; only the first
    unsatisfied category is 'current'.
    """
    placed_counts = Counter(product.category for _item, product in placed)
    infos: list[StepInfo] = []
    current_assigned = False
    for order, item in enumerate(plan.items, start=1):
        cat = item.category
        done_n = min(placed_counts.get(cat, 0), item.quantity)
        if done_n >= item.quantity:
            status = "done"
        elif not current_assigned:
            status = "current"
            current_assigned = True
        else:
            status = "pending"
        infos.append(
            StepInfo(
                key=cat, category=cat, title=_step_title(cat), order=order,
                status=status, quantity=item.quantity, placed_count=done_n,
            )
        )
    return infos


def completeness_pct(
    placed: list[tuple[PlacedItem, Product]], plan: LayoutPlan | None = None
) -> int:
    if plan is not None and plan.items:
        placed_counts = Counter(product.category for _item, product in placed)
        total = sum(item.quantity for item in plan.items) or 1
        got = sum(min(placed_counts.get(item.category, 0), item.quantity) for item in plan.items)
        return round(100 * got / total)
    # legacy fixed-essentials behaviour (no plan supplied)
    placed_categories = {product.category for _item, product in placed}
    total = sum(ESSENTIAL_WEIGHTS.values())
    got = sum(w for cat, w in ESSENTIAL_WEIGHTS.items() if cat in placed_categories)
    return round(100 * got / total)


def missing_essentials(
    placed: list[tuple[PlacedItem, Product]], plan: LayoutPlan | None = None
) -> list[tuple[str, str]]:
    placed_counts = Counter(product.category for _item, product in placed)
    if plan is not None and plan.items:
        return [
            (
                item.category,
                ESSENTIAL_REASONS.get(
                    item.category,
                    f"Your plan includes {CATEGORY_LABELS.get(item.category, item.category)}.",
                ),
            )
            for item in plan.items
            if placed_counts.get(item.category, 0) < item.quantity
        ]
    return [
        (cat, ESSENTIAL_REASONS[cat])
        for cat in ("sofa", "tv_unit", "rug", "coffee_table", "lighting")
        if cat not in placed_counts
    ]
