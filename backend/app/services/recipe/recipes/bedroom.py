"""Bedroom recipe - the first recipe-only room type (no legacy planner branch).

Built entirely from recipe data + reusable strategies/count rules:
  bed against a wall (focal_wall), nightstands mirrored beside it (beside_anchor +
  mirror_pair), wardrobe on a remaining wall, a centred rug, a single reading chair,
  and a table lamp resting ON a nightstand (on_surface). No decor.
"""

from app.services.recipe.models import CountRule, Recipe
from app.services.recipe.recipes import role

BEDROOM_RECIPE = Recipe(
    recipe_id="bedroom.standard",
    room_type="bedroom",
    focal_strategy="longest_wall",
    room_goals=["restful", "symmetry"],
    compose_secondary=False,  # no extra chair-group/table/lamp cluster in the open area
    roles=[
        role("primary_sleeping", "bed", "focal_wall",
             ["against_wall", "not_block_door"], essential=True),
        role("bedside_support", "side_table", "beside_anchor",
             params={"anchor_category": "bed"},
             count=CountRule(mode="mirror_pair", max=2),
             depends_on=["primary_sleeping"]),
        role("clothing_storage", "storage", "remaining_wall", ["not_block_door"]),
        role("floor_anchor", "rug", "center_area", ["centered"]),
        role("reading_nook", "accent_chair", "reading_corner",
             depends_on=["primary_sleeping"]),  # one chair in the empty corner opposite the bed
        role("bedside_lamp", "lighting", "on_surface",
             count=CountRule(mode="single"),
             depends_on=["bedside_support"]),  # a table lamp ON a nightstand
    ],
)
