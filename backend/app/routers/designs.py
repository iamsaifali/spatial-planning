from fastapi import APIRouter, Query

from app.models.api import (
    DesignCreateRequest,
    DesignCreateResponse,
    DesignResponse,
    DesignSummary,
)
from app.models.geometry import StrictModel
from app.routers._common import resolve_placed
from app.services.persistence import designs_repo

router = APIRouter(prefix="/designs", tags=["designs"])


class DesignListResponse(StrictModel):
    items: list[DesignSummary]


@router.post("", response_model=DesignCreateResponse)
def create_design(req: DesignCreateRequest) -> DesignCreateResponse:
    placed = resolve_placed(req.placed_items)
    total = sum(product.price for _item, product in placed)
    name = req.name or "My Living Room"
    payload = {
        "room": req.room.model_dump(),
        "placed_items": [item.model_dump() for item in req.placed_items],
        "preferences": req.preferences.model_dump(),
    }
    design_id = designs_repo.save_design(name, payload, total, len(placed))
    return DesignCreateResponse(design_id=design_id, share_path=f"/planner/{design_id}")


@router.get("", response_model=DesignListResponse)
def list_designs(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)
) -> DesignListResponse:
    return DesignListResponse(items=[DesignSummary(**d) for d in designs_repo.list_designs(limit, offset)])


@router.get("/{design_id}", response_model=DesignResponse)
def get_design(design_id: str) -> DesignResponse:
    return DesignResponse(**designs_repo.get_design(design_id))
