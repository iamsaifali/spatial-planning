from fastapi import APIRouter

from app.errors import AppError
from app.models.api import (
    MissingEssential,
    SuggestedUpgrade,
    SummaryLine,
    SummaryNarrative,
    SummaryRequest,
    SummaryResponse,
)
from app.models.products import CATEGORY_LABELS
from app.routers._common import resolve_currency, resolve_placed, to_display_amount
from app.services.ai import copy_service
from app.services.catalog import get_repository
from app.services.guide.flow import completeness_pct, missing_essentials
from app.services.plan import director
from app.services.spatial.analyze import analyze_room
from app.services.spatial.validate import validate_item

router = APIRouter(tags=["summary"])


@router.post("/summary", response_model=SummaryResponse)
async def summary(req: SummaryRequest) -> SummaryResponse:
    placed = resolve_placed(req.placed_items)
    analysis = analyze_room(req.room)
    repo = get_repository()
    # Completeness/missing-essentials are plan-relative when a plan exists; if planning
    # is unavailable (LLM-only), fall back to the fixed-essentials baseline (plan=None).
    try:
        layout, _plan_source = await director.get_plan(req.room, req.preferences, placed)
    except AppError:
        layout = None

    lines = [
        SummaryLine(product=product, pose=item, instance_id=item.instance_id, line_price=product.price)
        for item, product in placed
    ]
    total = sum(line.line_price for line in lines)
    by_category: dict[str, int] = {}
    for _item, product in placed:
        by_category[product.category] = by_category.get(product.category, 0) + product.price

    findings = []
    for item, product in placed:
        findings.extend(validate_item(analysis, placed, item, product))

    missing = [
        MissingEssential(category=cat, label=CATEGORY_LABELS[cat], reason=reason)
        for cat, reason in missing_essentials(placed, layout)
    ]

    upgrades: list[SuggestedUpgrade] = []
    for item, product in placed:
        better = [
            p
            for p in repo.in_category(product.category)
            if p.id != product.id
            and p.in_stock
            and p.rating >= product.rating + 0.2
            and product.price < p.price <= product.price * 1.8
            and abs(p.width_cm - product.width_cm) <= max(40.0, product.width_cm * 0.2)
        ]
        if better:
            target = max(better, key=lambda p: (p.rating, -p.price))
            upgrades.append(
                SuggestedUpgrade(
                    from_product_id=product.id,
                    from_name=product.name,
                    to_product=target,
                    delta=target.price - product.price,
                    reason=f"Rated {target.rating} vs {product.rating} - a similar size in a higher finish.",
                )
            )
    upgrades = sorted(upgrades, key=lambda u: -u.to_product.rating)[:2]

    pct = completeness_pct(placed, layout)
    display_currency = resolve_currency(req.currency)
    narrative_facts = {
        "currency": display_currency,
        "total_price_display": f"{display_currency} {to_display_amount(total, display_currency):,}",
        "item_count": len(lines),
        "total_price": total,
        "completeness_pct": pct,
        "missing": [m.label for m in missing],
        "room_area_m2": round(analysis.area_cm2 / 10_000.0, 1),
        "issue_count": sum(1 for f in findings if f.severity in ("error", "warning")),
        "upgrade_count": len(upgrades),
    }
    copy, source = await copy_service.generate("summary", narrative_facts)

    return SummaryResponse(
        items=lines,
        total_price=total,
        by_category=by_category,
        completeness_pct=pct,
        missing_essentials=missing,
        suggested_upgrades=upgrades,
        layout_findings=findings,
        narrative=SummaryNarrative(text=copy.get("narrative", ""), copy_source=source),  # type: ignore[arg-type]
    )
