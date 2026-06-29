"""Recipe registry / loader.

Recipes register on import (they are authored, versioned artifacts — never generated
at request time). Phase 1 ships living_room and majlis.
"""

from app.services.recipe.models import Recipe
from app.services.recipe.recipes.bedroom import BEDROOM_RECIPE
from app.services.recipe.recipes.living_room import LIVING_ROOM_RECIPE
from app.services.recipe.recipes.majlis import MAJLIS_RECIPE

_RECIPES: dict[str, Recipe] = {}


def register_recipe(recipe: Recipe) -> None:
    _RECIPES[recipe.room_type] = recipe


def get_recipe(room_type: str) -> Recipe | None:
    """Look up the recipe for a room type, or None if none is registered."""
    return _RECIPES.get(room_type)


def all_recipes() -> dict[str, Recipe]:
    return dict(_RECIPES)


register_recipe(LIVING_ROOM_RECIPE)
register_recipe(MAJLIS_RECIPE)
register_recipe(BEDROOM_RECIPE)
