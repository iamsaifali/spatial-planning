"""Phase 2 - recipe-driven planning in shadow/flag mode.

Proves the recipe path is equivalent to the legacy planner for the shipped room types,
that ASSIST_PLANNER_MODE behaves per-mode, that the gate still rejects, and that legacy
output is byte-identical to a golden captured BEFORE the refactor.
"""

import contextlib
import logging
import os

import pytest

from app.config import get_settings
from app.models.geometry import PlacedItem, Room
from app.models.preferences import Preferences
from app.models.validation import MUST_FIX_CODES
from app.services.catalog import get_repository
from app.services.recipe.equivalence import compare_layouts
from app.services.recommend import orchestrator
from app.services.recommend.orchestrator import (
    RecipeError,
    plan_assist_layout,
    plan_layout,
    plan_layout_from_recipe,
)
from app.services.spatial.analyze import analyze_room
from app.services.spatial.validate import validate_item

# Fixed inputs == those used for the golden capture (pre-refactor).
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

# Golden values. Living: legacy (one-of-each) vs recipe (area-scaled accent pieces).
GOLDEN_LIVING_PID = "lay_0e82d240e3"  # legacy planner
GOLDEN_LIVING_RECIPE = "lay_d2387a615b"  # recipe planner (area-scaled)
GOLDEN_MAJLIS_PID = "lay_4bdb683bb4"  # majlis (recipe == legacy)


@contextlib.contextmanager
def planner_mode(mode: str):
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


def _room(spec) -> Room:
    return Room.model_validate(spec)


# --- golden: legacy is byte-identical after the refactor --------------------------


def test_legacy_unchanged_vs_golden(catalog_repo):
    lr = plan_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    mj = plan_layout(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    assert lr.proposal_id == GOLDEN_LIVING_PID
    assert mj.proposal_id == GOLDEN_MAJLIS_PID


# --- recipe behaviour: majlis reproduces legacy; living scales beyond it ----------


def test_living_room_recipe_scales_beyond_legacy(catalog_repo):
    legacy = plan_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    recipe = plan_layout_from_recipe(_room(LIVING_ROOM), LIVING_PREFS, [])
    # recipe adds area-scaled accent pieces -> at least as many items as legacy
    assert len(recipe.placements) >= len(legacy.placements)
    assert recipe.proposal_id == GOLDEN_LIVING_RECIPE  # deterministic recipe golden
    assert not [f for f in recipe.placements if f.product.category == "custom"]
    assert not [f for f in recipe.findings if f.severity == "error"]


def test_majlis_recipe_equivalent_to_legacy(catalog_repo):
    legacy = plan_layout(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    recipe = plan_layout_from_recipe(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    cmp = compare_layouts(legacy, recipe)
    assert cmp.equivalent, cmp.diffs
    assert cmp.proposal_id_match
    assert recipe.proposal_id == GOLDEN_MAJLIS_PID


# --- modes -------------------------------------------------------------------------


def test_legacy_mode_returns_current(catalog_repo):
    with planner_mode("legacy"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert out.proposal_id == GOLDEN_LIVING_PID


def test_recipe_mode_returns_valid(catalog_repo):
    with planner_mode("recipe"):
        out = plan_assist_layout(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    assert out.totals.item_count >= 3
    assert not [f for f in out.findings if f.severity == "error"]
    assert out.proposal_id == GOLDEN_MAJLIS_PID  # recipe mode == legacy output


def test_shadow_mode_returns_legacy(catalog_repo):
    with planner_mode("shadow"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert out.proposal_id == GOLDEN_LIVING_PID


def test_shadow_mode_records_equivalent_comparison(catalog_repo, caplog):
    with planner_mode("shadow"), caplog.at_level(logging.INFO, logger="zory"):
        plan_assist_layout(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    assert "EQUIVALENT" in caplog.text
    assert "DIVERGENCE" not in caplog.text


# --- safety / fallback -------------------------------------------------------------


def test_recipe_path_raises_clearly_when_no_recipe(catalog_repo):
    # "dining" has no recipe -> a clear, actionable error
    with pytest.raises(RecipeError, match="dining"):
        plan_layout_from_recipe(_room(LIVING_ROOM), Preferences(room_type="dining"), [], room_type="dining")


def test_recipe_mode_falls_back_safely_for_unknown_room_type(catalog_repo):
    # recipe mode + a room_type with no recipe must NOT raise; it falls back to legacy
    with planner_mode("recipe"):
        out = plan_assist_layout(_room(LIVING_ROOM), Preferences(), [], room_type="dining")
    assert out.totals.item_count >= 1  # legacy fallback produced a valid layout


def test_recipe_mode_falls_back_for_categories_override(catalog_repo):
    with planner_mode("recipe"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [], categories=["sofa", "rug"])
    assert [p.category for p in out.placements] in (["sofa", "rug"], ["sofa"])


def test_shadow_swallows_recipe_failure(catalog_repo, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("induced recipe failure")

    monkeypatch.setattr(orchestrator, "plan_layout_from_recipe", boom)
    with planner_mode("shadow"), caplog.at_level(logging.ERROR, logger="zory"):
        out = plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    # user still gets the legacy result; failure is logged, not raised
    assert out.proposal_id == GOLDEN_LIVING_PID
    assert "recipe path failed" in caplog.text


# --- the gate still rejects in the recipe path ------------------------------------


def test_recipe_path_respects_validation_gate(catalog_repo):
    # whatever the recipe places, no placement may carry a hard (MUST_FIX) error
    recipe = plan_layout_from_recipe(_room(SALON), MAJLIS_PREFS, [], room_type="majlis")
    analysis = analyze_room(_room(SALON))
    repo = get_repository()
    placed: list = []
    for p in recipe.placements:
        item = PlacedItem(
            instance_id=p.instance_id, product_id=p.product_id,
            x=p.pose.x, y=p.pose.y, rotation_deg=p.pose.rotation_deg,
        )
        product = repo.require(p.product_id)
        findings = validate_item(analysis, placed, item, product)
        assert not [f for f in findings if f.code in MUST_FIX_CODES], (p.category, findings)
        placed.append((item, product))


def test_recipe_path_in_tiny_room_skips_without_crashing(catalog_repo):
    tiny = {"vertices": [[0, 0], [200, 0], [200, 200], [0, 200]],
            "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 20, "width_cm": 80}], "windows": []}
    out = plan_layout_from_recipe(_room(tiny), Preferences(), [])
    assert not [f for f in out.findings if f.severity == "error"]  # gate kept it clean
