import json as _json
import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django.setup()

from django.test import Client as _DjangoClient  # noqa: E402

from spatial_planning.config import get_settings  # noqa: E402
from spatial_planning.models.geometry import Door, Room, Window  # noqa: E402

# Tests run against the small, fixed fixture catalog (NOT the large production catalog),
# so golden layouts / counts stay stable as the real catalog grows.
TEST_CATALOG = "spatial_planning/data/catalog.json"


class ApiClient:
    """Thin adapter over Django's test client so tests keep the FastAPI-TestClient
    call style: `client.get(url, params=...)` and `client.post(url, json=...)`."""

    def __init__(self) -> None:
        self._c = _DjangoClient()

    def get(self, url, params=None):
        return self._c.get(url, data=params)

    def post(self, url, json=None):
        body = _json.dumps(json) if json is not None else ""
        return self._c.post(url, data=body, content_type="application/json")

    def delete(self, url):
        return self._c.delete(url)


def _setup_repo(monkeypatch):
    """Load the fixture catalog, then mark the Django lazy-bootstrap done so the request
    middleware won't reload the production catalog. The assist-only app is stateless (no DB)."""
    monkeypatch.setenv("CATALOG_PATH", TEST_CATALOG)
    get_settings.cache_clear()

    import spatial_planning.bootstrap as bootstrap
    from spatial_planning.services.catalog import CatalogRepository, set_repository
    from spatial_planning.services.spatial.analyze import clear_cache

    clear_cache()
    settings = get_settings()
    set_repository(CatalogRepository.load(settings.resolve(TEST_CATALOG), settings.resolve(settings.static_dir)))
    bootstrap._done = True
    return bootstrap


@pytest.fixture()
def rect_room() -> Room:
    """4.8 x 3.6 m room; door on the top wall, window on the bottom wall."""
    return Room(
        vertices=[(0, 0), (480, 0), (480, 360), (0, 360)],
        doors=[Door(id="d1", wall_index=0, offset_cm=40, width_cm=90, swing="inward", hinge="left")],
        windows=[Window(id="w1", wall_index=2, offset_cm=140, width_cm=180)],
    )


@pytest.fixture()
def l_room() -> Room:
    return Room(
        vertices=[(0, 0), (600, 0), (600, 300), (300, 300), (300, 480), (0, 480)],
        doors=[
            Door(id="d1", wall_index=0, offset_cm=60, width_cm=90),
            Door(id="d2", wall_index=4, offset_cm=80, width_cm=90),
        ],
        windows=[Window(id="w1", wall_index=5, offset_cm=100, width_cm=160)],
    )


@pytest.fixture()
def tiny_room() -> Room:
    return Room(
        vertices=[(0, 0), (200, 0), (200, 200), (0, 200)],
        doors=[Door(id="d1", wall_index=0, offset_cm=20, width_cm=80)],
    )


@pytest.fixture()
def bowtie_room() -> Room:
    return Room(vertices=[(0, 0), (400, 300), (400, 0), (0, 300)])


@pytest.fixture()
def busy_room() -> Room:
    """Doors eat every wall: no clear segment long enough for a standard sofa."""
    return Room(
        vertices=[(0, 0), (400, 0), (400, 300), (0, 300)],
        doors=[
            Door(id="d1", wall_index=0, offset_cm=20, width_cm=250),
            Door(id="d2", wall_index=1, offset_cm=70, width_cm=160),
            Door(id="d3", wall_index=2, offset_cm=75, width_cm=250),
            Door(id="d4", wall_index=3, offset_cm=50, width_cm=200),
        ],
    )


@pytest.fixture()
def catalog_repo():
    from spatial_planning.services.catalog import CatalogRepository, set_repository

    settings = get_settings()
    repo = CatalogRepository.load(
        settings.resolve(TEST_CATALOG), settings.resolve(settings.static_dir)  # fixture catalog
    )
    set_repository(repo)
    return repo


@pytest.fixture()
def client(monkeypatch):
    """API client for the assist-only app."""
    bootstrap = _setup_repo(monkeypatch)
    yield ApiClient()
    bootstrap._done = False
    get_settings.cache_clear()
