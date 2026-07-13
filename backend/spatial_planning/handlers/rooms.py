
from spatial_planning.models.analysis import AnalysisResponse, RoomValidateResponse
from spatial_planning.models.api import AnalyzeRequest
from spatial_planning.services.catalog import get_repository
from spatial_planning.services.spatial.analyze import analyze_room, to_response
from spatial_planning.services.spatial.normalize import collect_room_issues
from spatial_planning.services.spatial.zones import initial_zones



def validate_room(req: AnalyzeRequest) -> RoomValidateResponse:
    issues = collect_room_issues(req.room)
    return RoomValidateResponse(valid=not issues, issues=issues)


def analyze(req: AnalyzeRequest) -> AnalysisResponse:
    analysis = analyze_room(req.room)
    zones = initial_zones(analysis, get_repository().category_stats())
    return to_response(analysis, zones)
