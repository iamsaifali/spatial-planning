from fastapi import APIRouter

from app.models.api import AssistantRequest, AssistantResponse
from app.routers._common import resolve_placed
from app.services.ai import copy_service
from app.services.guide.flow import completeness_pct
from app.services.spatial.analyze import analyze_room
from app.services.spatial.normalize import collect_room_issues

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", response_model=AssistantResponse)
async def ask(req: AssistantRequest) -> AssistantResponse:
    placed = resolve_placed(req.placed_items)

    facts: dict = {
        "step_key": req.step_key,
        "placed_names": [p.name for _i, p in placed],
        "placed_categories": sorted({p.category for _i, p in placed}),
        "completeness_pct": completeness_pct(placed),
        "preferences": req.preferences.model_dump(exclude_none=True),
    }
    if not collect_room_issues(req.room):
        analysis = analyze_room(req.room)
        facts["room_area_m2"] = round(analysis.area_cm2 / 10_000.0, 1)
        facts["walls"] = len(analysis.walls)
        facts["doors"] = len(req.room.doors)
        facts["windows"] = len(req.room.windows)
        if analysis.longest_clear_wall_index is not None:
            facts["longest_clear_wall_index"] = analysis.longest_clear_wall_index

    copy, source = await copy_service.assistant_answer(req.question, facts)
    return AssistantResponse(
        answer=copy.get("answer", ""),
        related_tip=copy.get("related_tip"),
        facts_used=sorted(k for k in facts if facts[k] not in (None, [], {})),
        copy_source=source,  # type: ignore[arg-type]
    )
