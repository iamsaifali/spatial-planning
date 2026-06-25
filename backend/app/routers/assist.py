from fastapi import APIRouter

from app.models.api import AssistLayoutRequest, AssistLayoutResponse
from app.services.recommend.orchestrator import plan_assist_layout

router = APIRouter(prefix="/assist", tags=["assist"])


@router.post("/layout", response_model=AssistLayoutResponse)
def assist_layout(req: AssistLayoutRequest) -> AssistLayoutResponse:
    """Propose a complete furniture layout for the room.

    Deterministic geometry only: products come from the recommendation engine and
    poses from the spatial engine. No LLM/image model decides coordinates, and no
    saved design is mutated - the caller previews these as ghosts and accepts.
    """
    return plan_assist_layout(
        room=req.room,
        preferences=req.preferences,
        placed_items=req.placed_items,
        categories=req.categories,
        room_type=req.room_type,
    )
