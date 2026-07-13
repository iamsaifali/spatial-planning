
"""DRF views — the Django web layer for the ZORY spatial-planning backend.

Each view is a thin adapter: validate the request through the EXISTING Pydantic model,
call the EXISTING (framework-agnostic) FastAPI router function, and return its Pydantic
result as JSON. The endpoint logic itself is reused verbatim, so behaviour and the HTTP
contract are identical to the FastAPI app. Pydantic ValidationError / AppError raised
inside these calls are translated to the exact FastAPI error bodies by the DRF
exception handler (see exception_handler.py).
"""

import asyncio

from pydantic import BaseModel, Field
from rest_framework.response import Response
from rest_framework.views import APIView

from spatial_planning.models.api import (
    AnalyzeRequest,
    AssistLayoutRequest,
    AssistantRequest,
    CheckoutRequest,
    DesignCreateRequest,
    RenderRequest,
    StepRequest,
    SuggestRequest,
    SummaryRequest,
    ValidateItemRequest,
)
from spatial_planning.handlers import assistant as assistant_r
from spatial_planning.handlers import checkout as checkout_r
from spatial_planning.handlers import config as config_r
from spatial_planning.handlers import designs as designs_r
from spatial_planning.handlers import guide as guide_r
from spatial_planning.handlers import health as health_r
from spatial_planning.handlers import placement as placement_r
from spatial_planning.handlers import products as products_r
from spatial_planning.handlers import render as render_r
from spatial_planning.handlers import rooms as rooms_r
from spatial_planning.handlers import summary as summary_r
from spatial_planning.handlers.assist import assist_layout


def _json(model) -> Response:
    """Serialize a Pydantic result the same way FastAPI's response_model does."""
    return Response(model.model_dump(mode="json"))


def _run(coro):
    """Bridge the async FastAPI handlers into sync DRF views."""
    return asyncio.run(coro)


# --- health / config ---------------------------------------------------------
class HealthView(APIView):
    def get(self, request):
        return _json(health_r.health())


class ConfigView(APIView):
    def get(self, request):
        return _json(config_r.app_config())


# --- rooms -------------------------------------------------------------------
class RoomValidateView(APIView):
    def post(self, request):
        return _json(rooms_r.validate_room(AnalyzeRequest.model_validate(request.data)))


class RoomAnalyzeView(APIView):
    def post(self, request):
        return _json(rooms_r.analyze(AnalyzeRequest.model_validate(request.data)))


# --- guide -------------------------------------------------------------------
class GuideStepsView(APIView):
    def post(self, request):
        return _json(guide_r.steps(StepRequest.model_validate(request.data)))


class GuideStepView(APIView):
    def post(self, request, step_key):
        return _json(_run(guide_r.step(step_key, StepRequest.model_validate(request.data))))


# --- placement ---------------------------------------------------------------
class PlacementSuggestView(APIView):
    def post(self, request):
        return _json(placement_r.suggest(SuggestRequest.model_validate(request.data)))


class PlacementValidateView(APIView):
    def post(self, request):
        return _json(placement_r.validate(ValidateItemRequest.model_validate(request.data)))


# --- assist ------------------------------------------------------------------
class AssistLayoutView(APIView):
    def post(self, request):
        return _json(assist_layout(AssistLayoutRequest.model_validate(request.data)))


# --- products ----------------------------------------------------------------
class ProductQuery(BaseModel):
    """Mirrors the FastAPI Query(...) constraints on GET /products."""

    category: str | None = None
    style: str | None = None
    color: str | None = None
    material: str | None = None
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    in_stock: bool | None = None
    q: str | None = Field(default=None, max_length=80)
    room_type: str | None = None
    region: str | None = None
    luxury_tier: str | None = None
    sort: str = Field(default="relevance", pattern="^(relevance|price_asc|price_desc|rating)$")
    page: int = Field(default=1, ge=1, le=50)
    page_size: int = Field(default=24, ge=1, le=100)


class ProductsView(APIView):
    def get(self, request):
        query = ProductQuery.model_validate(request.query_params.dict())
        return _json(products_r.list_products(**query.model_dump()))


class ProductDetailView(APIView):
    def get(self, request, product_id):
        return _json(products_r.get_product(product_id))


# --- summary / render / assistant (async handlers) ---------------------------
class SummaryView(APIView):
    def post(self, request):
        return _json(_run(summary_r.summary(SummaryRequest.model_validate(request.data))))


class RenderView(APIView):
    def post(self, request):
        return _json(_run(render_r.render(RenderRequest.model_validate(request.data))))


class AssistantAskView(APIView):
    def post(self, request):
        return _json(_run(assistant_r.ask(AssistantRequest.model_validate(request.data))))


# --- designs -----------------------------------------------------------------
class DesignQuery(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class DesignsView(APIView):
    def post(self, request):
        return _json(designs_r.create_design(DesignCreateRequest.model_validate(request.data)))

    def get(self, request):
        query = DesignQuery.model_validate(request.query_params.dict())
        return _json(designs_r.list_designs(query.limit, query.offset))


class DesignDetailView(APIView):
    def get(self, request, design_id):
        return _json(designs_r.get_design(design_id))


# --- checkout / orders -------------------------------------------------------
class CheckoutView(APIView):
    def post(self, request):
        return _json(checkout_r.checkout(CheckoutRequest.model_validate(request.data)))


class OrderDetailView(APIView):
    def get(self, request, order_id):
        return _json(checkout_r.get_order(order_id))
