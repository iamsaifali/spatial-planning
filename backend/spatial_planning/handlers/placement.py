
from spatial_planning.models.api import SuggestRequest, ValidateItemRequest
from spatial_planning.models.validation import SuggestResponse, ValidateResponse
from spatial_planning.handlers._common import resolve_item, resolve_placed
from spatial_planning.services.catalog import get_repository
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.autofix import find_autofix, find_better_placement, suggest_pose
from spatial_planning.services.spatial.validate import validate_item



def suggest(req: SuggestRequest) -> SuggestResponse:
    placed = resolve_placed(req.placed_items)
    repo = get_repository()
    product = repo.require(req.product_id)
    analysis = analyze_room(req.room)
    pose, zone_id, alternatives = suggest_pose(
        analysis, placed, product, repo.category_stats(), req.zone_id
    )
    return SuggestResponse(pose=pose, zone_id=zone_id, alternatives=alternatives)


def validate(req: ValidateItemRequest) -> ValidateResponse:
    placed = resolve_placed(req.placed_items)
    repo = get_repository()
    product = resolve_item(req.item)
    analysis = analyze_room(req.room)

    findings = validate_item(analysis, placed, req.item, product)
    autofix = find_autofix(analysis, placed, req.item, product, findings)
    better = find_better_placement(analysis, placed, req.item, product, repo.category_stats())
    return ValidateResponse(findings=findings, autofix=autofix, better_placement=better)
