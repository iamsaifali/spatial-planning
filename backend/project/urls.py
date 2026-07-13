"""Standalone-runner URLconf.

Mounts the self-contained spatial_planning app at the root so the frontend keeps
calling http://localhost:8000/api/v1/... unchanged. When merged into the main Zory_ai
repo, mount the same include under a prefix instead, e.g.:
    path("spatial-planning/", include("spatial_planning.urls"))
"""

from django.urls import include, path

urlpatterns = [
    path("", include("spatial_planning.urls")),
]
