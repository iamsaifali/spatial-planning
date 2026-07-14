"""DRF views — the Django web layer for the ZORY spatial-planning backend (assist-only).

Each view is a thin adapter: validate the request through the EXISTING Pydantic model,
call the framework-agnostic handler, and return its Pydantic result as JSON. Pydantic
ValidationError / AppError raised inside these calls are translated to the exact error
bodies by the DRF exception handler (see exception_handler.py).
"""

from rest_framework.response import Response
from rest_framework.views import APIView

from spatial_planning.handlers import config as config_r
from spatial_planning.handlers import health as health_r
from spatial_planning.handlers.assist import assist_layout
from spatial_planning.models.api import AssistLayoutRequest


def _json(model) -> Response:
    """Serialize a Pydantic result the same way FastAPI's response_model did."""
    return Response(model.model_dump(mode="json"))


# --- health / config ---------------------------------------------------------
class HealthView(APIView):
    def get(self, request):
        return _json(health_r.health())


class ConfigView(APIView):
    def get(self, request):
        return _json(config_r.app_config())


# --- assist ------------------------------------------------------------------
class AssistLayoutView(APIView):
    def post(self, request):
        return _json(assist_layout(AssistLayoutRequest.model_validate(request.data)))
