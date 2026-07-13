"""URL routing — reproduces the FastAPI routes exactly, all under the `/api/v1` prefix
and with no trailing slash, so the frontend only swaps its base URL.
"""

from django.urls import path, re_path
from django.views.static import serve

from spatial_planning.config import get_settings
from spatial_planning import views

_settings = get_settings()
_static_dir = str(_settings.resolve(_settings.static_dir))

API = "api/v1/"

urlpatterns = [
    path(API + "health", views.HealthView.as_view()),
    path(API + "config", views.ConfigView.as_view()),
    path(API + "rooms/validate", views.RoomValidateView.as_view()),
    path(API + "rooms/analyze", views.RoomAnalyzeView.as_view()),
    path(API + "guide/steps", views.GuideStepsView.as_view()),
    path(API + "guide/step/<str:step_key>", views.GuideStepView.as_view()),
    path(API + "placement/suggest", views.PlacementSuggestView.as_view()),
    path(API + "placement/validate", views.PlacementValidateView.as_view()),
    path(API + "assist/layout", views.AssistLayoutView.as_view()),
    path(API + "products", views.ProductsView.as_view()),
    path(API + "products/<str:product_id>", views.ProductDetailView.as_view()),
    path(API + "summary", views.SummaryView.as_view()),
    path(API + "render", views.RenderView.as_view()),
    path(API + "assistant/ask", views.AssistantAskView.as_view()),
    path(API + "designs", views.DesignsView.as_view()),
    path(API + "designs/<str:design_id>", views.DesignDetailView.as_view()),
    path(API + "checkout", views.CheckoutView.as_view()),
    path(API + "orders/<str:order_id>", views.OrderDetailView.as_view()),
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": _static_dir}),
]
