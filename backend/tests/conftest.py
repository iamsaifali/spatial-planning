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
    from app.services.plan.director import clear_cache as clear_plan_cache
    from app.services.spatial.analyze import clear_cache

    clear_cache()
    clear_plan_cache()
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


# Canned, schema-valid family plan for exercising the LLM-only planning path offline.
_CANNED_PLAN = {
    "archetype": "family",
    "rationale": "test plan",
    "items": [
        {"category": "sofa", "quantity": 1, "priority": 1, "tier": "essential"},
        {"category": "tv_unit", "quantity": 1, "priority": 2, "tier": "essential"},
        {"category": "rug", "quantity": 1, "priority": 3, "tier": "essential"},
        {"category": "coffee_table", "quantity": 1, "priority": 4, "tier": "essential"},
        {"category": "side_table", "quantity": 2, "priority": 5, "tier": "non_essential"},
        {"category": "accent_chair", "quantity": 1, "priority": 6, "tier": "non_essential"},
        {"category": "lighting", "quantity": 2, "priority": 7, "tier": "non_essential"},
        {"category": "storage", "quantity": 1, "priority": 8, "tier": "non_essential"},
        {"category": "decor", "quantity": 2, "priority": 9, "tier": "non_essential"},
    ],
}


@pytest.fixture()
def llm_plan(monkeypatch):
    """Force the Director's LLM call to return the canned plan (and let copy fall back
    to templates), so the LLM-only planning path can be exercised without an API key."""
    async def _fake(kind, facts, instruction):
        return {**_CANNED_PLAN} if kind == "layout_plan" else None

    from app.services.ai import copy_service
    from app.services.plan import director

    monkeypatch.setattr(copy_service, "_llm_generate", _fake)
    director.clear_cache()
    return _CANNED_PLAN
