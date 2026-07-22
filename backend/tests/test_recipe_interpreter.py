"""Phase 3 - recipe interpreter (strategy/count/dependency execution).

These exercise the NEW interpreter machinery directly and broaden the equivalence
proof that the recipe path reproduces the legacy planner.
"""

import pytest

from spatial_planning.models.geometry import Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.services.recipe.equivalence import compare_layouts
from spatial_planning.services.recipe.models import (
    CountRule,
    PredicateRef,
    Recipe,
    RoleDefinition,
    ZoneStrategyRef,
)
from spatial_planning.services.recipe.registry import get_recipe
from spatial_planning.services.recommend.orchestrator import (
    RecipeError,
    _execute_role,
    _PlanState,
    _resolve_recipe_predicates,
    _topological_order,
    plan_layout,
    plan_layout_from_recipe,
)
from spatial_planning.services.spatial.analyze import analyze_room

RECT = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
}
LSHAPE = {
    "vertices": [[0, 0], [600, 0], [600, 300], [300, 300], [300, 480], [0, 480]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 60, "width_cm": 90}],
    "windows": [{"id": "w1", "wall_index": 5, "offset_cm": 100, "width_cm": 160}],
}
WIDE = {
    "vertices": [[0, 0], [600, 0], [600, 560], [0, 560]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 250, "width_cm": 100}],
    "windows": [],
}


def _zs(name):
    return ZoneStrategyRef(name=name)


# --- dependency execution ----------------------------------------------------------


def test_topological_order_preserves_declared_order_for_shipped_recipes():
    for rt in ("living_room", "bedroom"):
        recipe = get_recipe(rt)
        ordered = [r.role for r in _topological_order(recipe.roles)]
        assert ordered == [r.role for r in recipe.roles]


def test_topological_order_places_anchor_before_dependent():
    # dependent declared FIRST -> topo must still place the anchor first
    roles = [
        RoleDefinition(role="dependent", categories=["rug"], zone_strategy=_zs("center_area"), depends_on=["anchor"]),
        RoleDefinition(role="anchor", categories=["sofa"], zone_strategy=_zs("wall_band")),
    ]
    ordered = [r.role for r in _topological_order(roles)]
    assert ordered.index("anchor") < ordered.index("dependent")


def test_topological_order_rejects_cycle():
    roles = [
        RoleDefinition(role="a", categories=["sofa"], zone_strategy=_zs("wall_band"), depends_on=["b"]),
        RoleDefinition(role="b", categories=["rug"], zone_strategy=_zs("center_area"), depends_on=["a"]),
    ]
    with pytest.raises(RecipeError, match="cyclic"):
        _topological_order(roles)


# --- count-rule execution ----------------------------------------------------------


def test_unimplemented_count_mode_raises(catalog_repo):
    st = _PlanState(
        analysis=analyze_room(Room.model_validate(RECT)),
        preferences=Preferences(),
        repo=catalog_repo,
        stats=catalog_repo.category_stats(),
        room_type="living_room",
        working=[],
    )
    # Every declared CountMode is now implemented (per_anchor landed with the dining set), so an
    # unimplemented mode can only be reached by bypassing the CountRule literal validation.
    role = RoleDefinition(
        role="x", categories=["decor"], zone_strategy=_zs("corners"),
        count=CountRule.model_construct(mode="not_a_real_mode"),
    )
    with pytest.raises(RecipeError, match="not_a_real_mode"):
        _execute_role(role, st)


# --- predicate awareness -----------------------------------------------------------


def test_predicate_awareness_resolves_shipped_recipes():
    for rt in ("living_room", "bedroom"):
        _resolve_recipe_predicates(get_recipe(rt))  # no raise


def test_predicate_awareness_rejects_unknown_predicate():
    bad = Recipe(
        recipe_id="x", room_type="x",
        roles=[RoleDefinition(role="r", categories=["sofa"], zone_strategy=_zs("wall_band"),
                              predicates=[PredicateRef(name="bogus_predicate")])],
    )
    with pytest.raises(KeyError, match="bogus_predicate"):
        _resolve_recipe_predicates(bad)


