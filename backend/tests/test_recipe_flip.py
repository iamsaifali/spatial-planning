"""Phase 6 - flip the default planner to recipe, with rollback + safety.

Proves the default is now recipe, all three modes still work (rollback intact), recipe
mode reproduces the golden proposals, categories overrides route to legacy, recipe
failures surface clearly, and production safety logging is emitted.
"""

import contextlib
import logging
import os

import pytest

import app.services.recommend.orchestrator as orch
from app.config import get_settings
from app.models.geometry import Room
from app.models.preferences import Preferences
from app.services.recommend.orchestrator import plan_assist_layout, plan_layout

GOLDEN_LIVING_PID = "lay_0e82d240e3"  # legacy (one-of-each) - rollback path
GOLDEN_LIVING_RECIPE = "lay_d2387a615b"  # recipe (area-scaled accent pieces) - production
GOLDEN_MAJLIS_PID = "lay_4bdb683bb4"

LIVING_ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
    "wall_height_cm": 270,
}
SALON = {
    "vertices": [[0, 0], [600, 0], [600, 560], [0, 560]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 250, "width_cm": 100}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 200, "width_cm": 180}],
    "wall_height_cm": 300,
}
LIVING_PREFS = Preferences(styles=["modern"], budget_tier="mid", total_budget=8000, room_purpose="entertaining")
MAJLIS_PREFS = Preferences(
    room_type="majlis", region="saudi_arabia", styles=["majlis", "luxury"],
    luxury_tier="luxury", formality="formal", seating_capacity=10,
)


@contextlib.contextmanager
def planner_mode(mode):
    prev = os.environ.get("ASSIST_PLANNER_MODE")
    os.environ["ASSIST_PLANNER_MODE"] = mode
    get_settings.cache_clear()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("ASSIST_PLANNER_MODE", None)
        else:
            os.environ["ASSIST_PLANNER_MODE"] = prev
        get_settings.cache_clear()


def _room(spec):
    return Room.model_validate(spec)


# --- the flip ----------------------------------------------------------------------


def test_default_planner_mode_is_recipe(monkeypatch):
    monkeypatch.delenv("ASSIST_PLANNER_MODE", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().assist_planner_mode == "recipe"
    finally:
        get_settings.cache_clear()


def test_recipe_mode_returns_golden(catalog_repo):
    with planner_mode("recipe"):
        lr = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
        mj = plan_assist_layout(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    assert lr.proposal_id == GOLDEN_LIVING_RECIPE  # recipe = area-scaled
    assert mj.proposal_id == GOLDEN_MAJLIS_PID


# --- rollback paths still work -----------------------------------------------------


def test_legacy_mode_still_works(catalog_repo):
    with planner_mode("legacy"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert out.proposal_id == GOLDEN_LIVING_PID


def test_shadow_mode_still_returns_legacy(catalog_repo, caplog):
    with planner_mode("shadow"), caplog.at_level(logging.INFO, logger="zory"):
        out = plan_assist_layout(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    assert out.proposal_id == GOLDEN_MAJLIS_PID
    assert "EQUIVALENT" in caplog.text  # shadow comparison still runs


# --- categories override decision (Option A: route to legacy) ----------------------


def test_categories_override_routes_to_legacy_in_recipe_mode(catalog_repo, monkeypatch):
    called = []
    real_recipe = orch.plan_layout_from_recipe
    monkeypatch.setattr(orch, "plan_layout_from_recipe", lambda *a, **k: called.append(1) or real_recipe(*a, **k))

    with planner_mode("recipe"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [], categories=["sofa", "rug"])

    # recipe planner was NOT used; result equals the legacy categories-override output
    assert called == []
    legacy = plan_layout(_room(LIVING_ROOM), LIVING_PREFS, [], categories=["sofa", "rug"])
    assert out.proposal_id == legacy.proposal_id
    assert [p.category for p in out.placements] in (["sofa", "rug"], ["sofa"])


# --- failure behaviour per mode ----------------------------------------------------


def test_recipe_mode_surfaces_failure_clearly(catalog_repo, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("induced recipe failure")

    monkeypatch.setattr(orch, "plan_layout_from_recipe", boom)
    with planner_mode("recipe"), caplog.at_level(logging.ERROR, logger="zory"):
        with pytest.raises(RuntimeError, match="induced recipe failure"):
            plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert "recipe planner FAILED" in caplog.text


def test_legacy_mode_unaffected_by_recipe_failure(catalog_repo, monkeypatch):
    monkeypatch.setattr(orch, "plan_layout_from_recipe", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with planner_mode("legacy"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert out.proposal_id == GOLDEN_LIVING_PID  # legacy never touches the recipe path


def test_shadow_mode_swallows_recipe_failure(catalog_repo, monkeypatch):
    monkeypatch.setattr(orch, "plan_layout_from_recipe", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with planner_mode("shadow"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert out.proposal_id == GOLDEN_LIVING_PID  # user still gets legacy


# --- production safety logging -----------------------------------------------------


def test_recipe_mode_emits_safety_log(catalog_repo, caplog):
    with planner_mode("recipe"), caplog.at_level(logging.INFO, logger="zory"):
        plan_assist_layout(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    text = caplog.text
    assert "assist recipe[majlis]" in text
    assert GOLDEN_MAJLIS_PID in text
    assert "recipe=majlis.standard@" in text
    assert "placements=" in text and "skipped=" in text and "hard=" in text
