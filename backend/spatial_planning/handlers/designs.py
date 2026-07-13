
from spatial_planning.models.api import (
    DesignCreateRequest,
    DesignCreateResponse,
    DesignResponse,
    DesignSummary,
)
from spatial_planning.models.geometry import StrictModel
from spatial_planning.handlers._common import resolve_placed
from spatial_planning.services.persistence import designs_repo



class DesignListResponse(StrictModel):
    items: list[DesignSummary]


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


def list_designs(
    limit: int = 20, offset: int = 0
) -> DesignListResponse:
    return DesignListResponse(items=[DesignSummary(**d) for d in designs_repo.list_designs(limit, offset)])


def get_design(design_id: str) -> DesignResponse:
    return DesignResponse(**designs_repo.get_design(design_id))
