"""Phase 1 recipe framework — infrastructure only.

Proves the codebase understands recipes AND that they are a faithful shadow of the
current planner. No existing file was changed, so behaviour is unchanged by
construction; these tests lock in the equivalence the migration relies on.
"""

import pytest

from app.models.geometry import Room
from app.services.guide.flow import LIVING_ROOM_SEQUENCE, MAJLIS_SEQUENCE, sequence_for_room_type
from app.services.recipe import (
    PREDICATE_REGISTRY,
    STRATEGY_REGISTRY,
    all_recipes,
    assert_recipe_matches_current,
    get_recipe,
    resolve_predicate,
    resolve_recipe_references,
    resolve_strategy,
)
from app.services.spatial.analyze import analyze_room
from app.services.spatial.zones import zones_for_category


# --- recipes load -----------------------------------------------------------------


def test_living_room_recipe_loads():
    r = get_recipe("living_room")
    assert r is not None and r.recipe_id == "living_room.standard"
    assert r.roles[0].role == "primary_seating"


def test_majlis_recipe_loads():
    r = get_recipe("majlis")
    assert r is not None and r.recipe_id == "majlis.standard"
    assert r.roles[0].role == "perimeter_seating"


def test_unknown_room_type_returns_none():
    assert get_recipe("dining") is None  # not registered yet


def test_registry_has_registered_recipes():
    assert set(all_recipes()) == {"living_room", "majlis", "bedroom"}


# --- references resolve ------------------------------------------------------------


def test_all_strategy_references_resolve():
    for recipe in all_recipes().values():
        for role in recipe.roles:
            assert resolve_strategy(role.zone_strategy.name).name == role.zone_strategy.name


def test_all_predicate_references_resolve():
    for recipe in all_recipes().values():
        for role in recipe.roles:
            for pred in role.predicates:
                assert resolve_predicate(pred.name).name == pred.name


def test_resolve_recipe_references_passes_for_shipped_recipes():
    for recipe in all_recipes().values():
        resolve_recipe_references(recipe)  # raises on any unknown reference


def test_unknown_references_raise():
    with pytest.raises(KeyError):
        resolve_strategy("does_not_exist")
    with pytest.raises(KeyError):
        resolve_predicate("does_not_exist")


def test_hard_predicates_map_to_real_finding_codes():
    from app.models.validation import MUST_FIX_CODES

    hard = [p for p in PREDICATE_REGISTRY.values() if p.kind == "hard"]
    assert hard, "expected some hard predicates"
    for p in hard:
        # every hard predicate links to a gate Finding code; door/overlap/bounds/walkway
        assert p.finding_code is not None
    # the gate's must-fix codes are all reachable through hard predicates
    mapped = {p.finding_code for p in PREDICATE_REGISTRY.values() if p.finding_code}
    assert MUST_FIX_CODES <= mapped


# --- fidelity: recipe reproduces current behaviour ---------------------------------


def test_living_room_recipe_matches_current_sequence():
    assert get_recipe("living_room").category_sequence() == LIVING_ROOM_SEQUENCE
    assert get_recipe("living_room").category_sequence() == sequence_for_room_type("living_room")


def test_majlis_recipe_matches_current_sequence():
    assert get_recipe("majlis").category_sequence() == MAJLIS_SEQUENCE
    assert get_recipe("majlis").category_sequence() == sequence_for_room_type("majlis")


def test_fidelity_assertion_passes_for_both():
    assert_recipe_matches_current("living_room")
    assert_recipe_matches_current("majlis")


def test_strategy_resolver_produces_identical_zones_to_current(catalog_repo):
    """A strategy reference resolves to zone-producing code byte-identical to today."""
    room = Room.model_validate(
        {
            "vertices": [[0, 0], [600, 0], [600, 460], [0, 460]],
            "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 250, "width_cm": 100}],
            "windows": [],
            "wall_height_cm": 300,
        }
    )
    analysis = analyze_room(room)
    stats = catalog_repo.category_stats()

    recipe = get_recipe("majlis")
    seating = recipe.roles[0]  # perimeter_seating -> "perimeter_walls" -> sofa
    strategy = resolve_strategy(seating.zone_strategy.name)

    via_recipe = strategy.resolver("sofa", "majlis", analysis, [], stats, seating.zone_strategy.params)
    via_current = zones_for_category("sofa", analysis, [], stats, room_type="majlis")

    assert [z.id for z in via_recipe] == [z.id for z in via_current]
    assert [z.reason_codes for z in via_recipe] == [z.reason_codes for z in via_current]


# --- count rules represent current behaviour ---------------------------------------


def test_count_modes_per_recipe():
    """The distinctive count modes each recipe relies on."""
    modes = {rt: {r.role: r.count.mode for r in get_recipe(rt).roles} for rt in all_recipes()}
    # multi-instance signatures
    assert modes["majlis"]["perimeter_seating"] == "until_target"
    assert modes["bedroom"]["bedside_support"] == "mirror_pair"
    # accent pieces scale with area in living_room + bedroom
    assert modes["living_room"]["accent"] == "fill_available"
    assert modes["living_room"]["ambient_light"] == "fill_available"
    assert modes["bedroom"]["accent"] == "fill_available"
    # essentials stay single
    assert modes["living_room"]["primary_seating"] == "single"
    assert modes["bedroom"]["primary_sleeping"] == "single"
    assert modes["majlis"]["floor_anchor"] == "single"
