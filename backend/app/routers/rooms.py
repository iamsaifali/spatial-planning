from fastapi import APIRouter

from app.models.analysis import AnalysisResponse, RoomValidateResponse
from app.models.api import AnalyzeRequest
from app.services.catalog import get_repository
from app.services.spatial.analyze import analyze_room, to_response
from app.services.spatial.normalize import collect_room_issues
from app.services.spatial.zones import initial_zones

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("/validate", response_model=RoomValidateResponse)
def validate_room(req: AnalyzeRequest) -> RoomValidateResponse:
    issues = collect_room_issues(req.room)
    return RoomValidateResponse(valid=not issues, issues=issues)


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(req: AnalyzeRequest) -> AnalysisResponse:
    analysis = analyze_room(req.room)
    zones = initial_zones(analysis, get_repository().category_stats())
    return to_response(analysis, zones)
