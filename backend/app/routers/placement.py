from fastapi import APIRouter

from app.models.api import SuggestRequest, ValidateItemRequest
from app.models.validation import SuggestResponse, ValidateResponse
from app.routers._common import resolve_item, resolve_placed
from app.services.catalog import get_repository
from app.services.majlis.validate import MAJLIS_SUPPRESSED_CODES
from app.services.majlis.zones import majlis_suggest_pose
from app.services.spatial.analyze import analyze_room
from app.services.spatial.autofix import find_autofix, find_better_placement, suggest_pose
from app.services.spatial.validate import validate_item

router = APIRouter(prefix="/placement", tags=["placement"])


@router.post("/suggest", response_model=SuggestResponse)
def suggest(req: SuggestRequest) -> SuggestResponse:
    placed = resolve_placed(req.placed_items)
    repo = get_repository()
    product = repo.require(req.product_id)
    analysis = analyze_room(req.room)
    if req.preferences.room_type == "majlis":
        pose, zone_id, alternatives = majlis_suggest_pose(analysis, placed, product, repo.category_stats())
    else:
        pose, zone_id, alternatives = suggest_pose(
            analysis, placed, product, repo.category_stats(), req.zone_id
        )
    return SuggestResponse(pose=pose, zone_id=zone_id, alternatives=alternatives)


@router.post("/validate", response_model=ValidateResponse)
def validate(req: ValidateItemRequest) -> ValidateResponse:
    placed = resolve_placed(req.placed_items)
    repo = get_repository()
    product = resolve_item(req.item)
    analysis = analyze_room(req.room)

    findings = validate_item(analysis, placed, req.item, product)
    if req.preferences.room_type == "majlis":
        # majlis uses a different rule set: drop the family TV/clearance/dominates findings,
        # and don't offer a family "better placement" (it would suggest a non-perimeter spot).
        findings = [f for f in findings if f.code not in MAJLIS_SUPPRESSED_CODES]
        better = None
    else:
        better = find_better_placement(analysis, placed, req.item, product, repo.category_stats())
    autofix = find_autofix(analysis, placed, req.item, product, findings)
    return ValidateResponse(findings=findings, autofix=autofix, better_placement=better)
