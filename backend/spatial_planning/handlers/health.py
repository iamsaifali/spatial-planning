
from spatial_planning.config import get_settings
from spatial_planning.models.api import HealthResponse



def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.version,
        llm_enabled=settings.llm_enabled,
        render_enabled=settings.llm_enabled,
    )
