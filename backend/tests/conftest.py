import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models.geometry import Door, Room, Window


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
    from app.services.catalog import CatalogRepository, set_repository

    settings = get_settings()
    repo = CatalogRepository.load(
        settings.resolve(settings.catalog_path), settings.resolve(settings.static_dir)
    )
    set_repository(repo)
    return repo


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    from app.main import create_app
    from app.services.spatial.analyze import clear_cache

    clear_cache()
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
