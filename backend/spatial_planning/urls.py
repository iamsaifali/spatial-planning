"""URL routing (assist-only) — under the `/api/v1` prefix, no trailing slash."""

from django.urls import path, re_path
from django.views.static import serve

from spatial_planning import views
from spatial_planning.config import get_settings

_settings = get_settings()
_static_dir = str(_settings.resolve(_settings.static_dir))

API = "api/v1/"

urlpatterns = [
    path(API + "health", views.HealthView.as_view()),
    path(API + "config", views.ConfigView.as_view()),
    path(API + "assist/layout", views.AssistLayoutView.as_view()),
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": _static_dir}),
]
