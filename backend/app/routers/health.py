from fastapi import APIRouter

from app.config import get_settings
from app.models.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.version,
        llm_enabled=settings.llm_enabled,
        render_enabled=settings.llm_enabled,
    )
