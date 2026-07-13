"""Migration adapter — lets the recipe layer REPRESENT current behaviour without
replacing it.

Phase 1 keeps the live planner (orchestrator + flow.sequence_for_room_type + the zone
dispatch) exactly as-is. This adapter is the bridge between recipe-world and the
current code:

  * recipe_sequence()           - the category order a recipe encodes
  * resolve_recipe_references()  - every strategy/predicate name maps to real code
  * assert_recipe_matches_current() - the recipe reproduces the live planner's sequence

Phase 2 will flip the planner to drive placement THROUGH this layer (recipe -> role
graph -> strategy resolver -> select -> gate). Until then the adapter is exercised only
by tests, so production behaviour is unchanged.

        Old Planner  ->  Recipe Adapter  ->  Current Logic
   (not: Recipe Interpreter replacing everything)
"""

from spatial_planning.services.guide.flow import sequence_for_room_type
from spatial_planning.services.recipe.models import Recipe
from spatial_planning.services.recipe.predicates import resolve_predicate
from spatial_planning.services.recipe.registry import get_recipe
from spatial_planning.services.recipe.strategies import resolve_strategy


def recipe_sequence(recipe: Recipe) -> list[str]:
    """The primary-category placement order this recipe encodes."""
    return recipe.category_sequence()


def resolve_recipe_references(recipe: Recipe) -> None:
    """Raise if any strategy/predicate reference in the recipe is unknown.

    Proves the recipe's references are all backed by real, registered code.
    """
    for role in recipe.roles:
        resolve_strategy(role.zone_strategy.name)
        for predicate in role.predicates:
            resolve_predicate(predicate.name)


def assert_recipe_matches_current(room_type: str) -> None:
    """Fidelity gate: the registered recipe must reproduce the live planner's sequence
    and every reference must resolve. This is the Phase-1 safety net — if a recipe ever
    diverges from current behaviour, this fails loudly (in tests)."""
    recipe = get_recipe(room_type)
    if recipe is None:
        raise AssertionError(f"No recipe registered for room_type '{room_type}'")
    resolve_recipe_references(recipe)
    current = sequence_for_room_type(room_type)
    derived = recipe_sequence(recipe)
    if derived != current:
        raise AssertionError(
            f"Recipe '{recipe.recipe_id}' sequence {derived} != current planner {current}"
        )
