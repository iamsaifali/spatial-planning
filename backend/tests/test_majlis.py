"""P0 scaffold: room_type dispatch routes 'majlis' to the (stub) Majlis engine, while
the default 'living_room' is unchanged and isolated from it."""

from app.models.preferences import Preferences

API = "/api/v1"
ROOM = {"vertices": [[0, 0], [500, 0], [500, 400], [0, 400]], "doors": [], "windows": []}


def test_room_type_defaults_to_living_room():
    # Existing requests / saved designs omit room_type -> stay on the family engine.
    assert Preferences().room_type == "living_room"
    assert Preferences(room_purpose="family", seating_capacity=5).room_type == "living_room"


def test_majlis_plan_returns_stub_without_llm(client):
    """A majlis plan request resolves via the Majlis engine (no LLM) and returns the P0
    'coming soon' stub - proving the dispatch took the majlis branch, not the family
    director (which would 503 here without an LLM)."""
    body = {"room": ROOM, "preferences": {"styles": ["modern"], "room_type": "majlis"}, "placed_items": []}
    r = client.post(f"{API}/guide/plan", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["plan"]["archetype"] == "majlis"
    assert data["plan"]["items"] == []
    assert data["steps"] == []
    assert "coming soon" in (data["plan"]["seating_note"] or "").lower()


def test_majlis_engine_does_not_touch_family_plan_cache():
    """The Majlis stub must not write into the family director's plan cache."""
    from app.models.geometry import Room
    from app.services.majlis import plan as majlis_plan
    from app.services.plan import director
    from app.services.spatial.analyze import analyze_room

    director.clear_cache()
    room = Room(vertices=[[0, 0], [500, 0], [500, 400], [0, 400]], doors=[], windows=[], wall_height_cm=270)
    prefs = Preferences(room_type="majlis")
    majlis_plan.get_majlis_plan(room, prefs, [])
    key = f"{analyze_room(room).analysis_hash}:{director._prefs_hash(prefs)}"  # noqa: SLF001
    assert director._plan_cache.get(key) is None  # noqa: SLF001
