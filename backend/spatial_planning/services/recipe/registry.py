"""Recipe registry / loader.

Recipes register on import (they are authored, versioned artifacts — never generated
at request time). Ships living_room and bedroom.
"""

from spatial_planning.services.recipe.models import Recipe
from spatial_planning.services.recipe.recipes.bedroom import BEDROOM_RECIPE
from spatial_planning.services.recipe.recipes.living_room import LIVING_ROOM_RECIPE

_RECIPES: dict[str, Recipe] = {}


def register_recipe(recipe: Recipe) -> None:
    _RECIPES[recipe.room_type] = recipe


def get_recipe(room_type: str) -> Recipe | None:
    """Look up the recipe for a room type, or None if none is registered."""
    return _RECIPES.get(room_type)


def all_recipes() -> dict[str, Recipe]:
    return dict(_RECIPES)


register_recipe(LIVING_ROOM_RECIPE)
register_recipe(BEDROOM_RECIPE)
