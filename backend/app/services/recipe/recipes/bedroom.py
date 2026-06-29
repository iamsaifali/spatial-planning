"""Bedroom recipe - the first recipe-only room type (no legacy planner branch).

Built entirely from recipe data + reusable strategies/count rules:
  bed against a wall (focal_wall), nightstands mirrored beside it (beside_anchor +
  mirror_pair), wardrobe on a remaining wall, a centred rug, a corner reading chair,
  and corner lighting/decor.
"""

from app.services.recipe.models import CountRule, Recipe
from app.services.recipe.recipes import role

BEDROOM_RECIPE = Recipe(
    recipe_id="bedroom.standard",
    room_type="bedroom",
    focal_strategy="longest_wall",
    room_goals=["restful", "symmetry"],
    compose_secondary=True,  # large bedrooms get a reading nook in the open area
    roles=[
        role("primary_sleeping", "bed", "focal_wall",
             ["against_wall", "not_block_door"], essential=True),
        role("bedside_support", "side_table", "beside_anchor",
             params={"anchor_category": "bed"},
             count=CountRule(mode="mirror_pair", max=2),
             depends_on=["primary_sleeping"]),
        role("clothing_storage", "storage", "remaining_wall", ["not_block_door"]),
        role("floor_anchor", "rug", "center_area", ["centered"]),
        role("reading_nook", "accent_chair", "around_anchor",
             count=CountRule(mode="fill_available", per_area_m2=18, max=2)),
        role("ambient_light", "lighting", "corners",
             count=CountRule(mode="fill_available", per_area_m2=12, max=2)),
        role("accent", "decor", "corners",
             count=CountRule(mode="fill_available", per_area_m2=10, max=4)),
    ],
)
