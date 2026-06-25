"""Recipe framework (Phase 1: infrastructure only).

The codebase now *understands* recipes — authored, registered, and proven to be a
faithful shadow of the current planner — but the planner does NOT consume them yet.
That flip is Phase 2.
"""

from app.services.recipe.adapter import (
    assert_recipe_matches_current,
    recipe_sequence,
    resolve_recipe_references,
)
from app.services.recipe.models import (
    CountRule,
    PredicateRef,
    Recipe,
    RoleDefinition,
    ZoneStrategyRef,
)
from app.services.recipe.predicates import PREDICATE_REGISTRY, Predicate, resolve_predicate
from app.services.recipe.registry import all_recipes, get_recipe, register_recipe
from app.services.recipe.strategies import STRATEGY_REGISTRY, ZoneStrategy, resolve_strategy

__all__ = [
    "Recipe",
    "RoleDefinition",
    "CountRule",
    "ZoneStrategyRef",
    "PredicateRef",
    "get_recipe",
    "all_recipes",
    "register_recipe",
    "resolve_strategy",
    "STRATEGY_REGISTRY",
    "ZoneStrategy",
    "resolve_predicate",
    "PREDICATE_REGISTRY",
    "Predicate",
    "recipe_sequence",
    "resolve_recipe_references",
    "assert_recipe_matches_current",
]
