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
    for rt in ("living_room", "majlis"):
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


def test_until_target_seating_reproduces_legacy(catalog_repo):
    # the generic until_target executor must match the legacy Majlis seating loop
    room = Room.model_validate(WIDE)
    prefs = Preferences(room_type="majlis", seating_capacity=10)
    legacy = plan_layout(room, prefs, [], room_type="majlis")
    recipe = plan_layout_from_recipe(room, prefs, [], room_type="majlis")
    legacy_sofas = [p.product_id for p in legacy.placements if p.category == "sofa"]
    recipe_sofas = [p.product_id for p in recipe.placements if p.category == "sofa"]
    assert legacy_sofas == recipe_sofas and len(legacy_sofas) >= 2


def test_unimplemented_count_mode_raises(catalog_repo):
    st = _PlanState(
        analysis=analyze_room(Room.model_validate(RECT)),
        preferences=Preferences(),
        repo=catalog_repo,
        stats=catalog_repo.category_stats(),
        room_type="living_room",
        working=[],
    )
    role = RoleDefinition(
        role="x", categories=["decor"], zone_strategy=_zs("corners"),
        count=CountRule(mode="per_anchor"),
    )
    with pytest.raises(RecipeError, match="per_anchor"):
        _execute_role(role, st)


# --- predicate awareness -----------------------------------------------------------


def test_predicate_awareness_resolves_shipped_recipes():
    for rt in ("living_room", "majlis"):
        _resolve_recipe_predicates(get_recipe(rt))  # no raise


def test_predicate_awareness_rejects_unknown_predicate():
    bad = Recipe(
        recipe_id="x", room_type="x",
        roles=[RoleDefinition(role="r", categories=["sofa"], zone_strategy=_zs("wall_band"),
                              predicates=[PredicateRef(name="bogus_predicate")])],
    )
    with pytest.raises(KeyError, match="bogus_predicate"):
        _resolve_recipe_predicates(bad)


# --- broadened equivalence ---------------------------------------------------------


def test_interpreter_equivalent_across_rooms_and_prefs(catalog_repo):
    # Majlis still mirrors the legacy planner exactly (its recipe uses single +
    # until_target, both of which reproduce legacy). living_room/bedroom intentionally
    # diverge now (area-scaled accent pieces), so they are NOT compared here.
    cases = [
        (WIDE, "majlis", Preferences(room_type="majlis", seating_capacity=8)),
        (WIDE, "majlis", Preferences(room_type="majlis")),  # area-based default target
        (RECT, "majlis", Preferences(room_type="majlis", seating_capacity=6)),
        (LSHAPE, "majlis", Preferences(room_type="majlis", luxury_tier="luxury")),
    ]
    for spec, rt, prefs in cases:
        room = Room.model_validate(spec)
        legacy = plan_layout(room, prefs, [], room_type=rt)
        recipe = plan_layout_from_recipe(room, prefs, [], room_type=rt)
        cmp = compare_layouts(legacy, recipe)
        assert cmp.equivalent, (spec["vertices"][1], rt, cmp.diffs)
        assert cmp.proposal_id_match, (rt, prefs)
