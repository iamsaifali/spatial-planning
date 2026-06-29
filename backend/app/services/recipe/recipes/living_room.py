"""Living-room recipe — mirrors the current LIVING_ROOM_SEQUENCE exactly.

Role order == category order in app/services/guide/flow.py::LIVING_ROOM_SEQUENCE
(sofa, tv_unit, rug, coffee_table, side_table, accent_chair, lighting, storage, decor).
The adapter asserts this equivalence; do not reorder without updating the source.
"""

from app.services.recipe.models import CountRule, Recipe
from app.services.recipe.recipes import role

# Accent roles scale with room area (fill_available): a bigger room gets more side
# tables / accent chairs / lamps / decor, a small room gets one of each. The essentials
# (sofa, tv, rug, coffee table, storage) stay single. (The legacy planner is one-of-each
# across the board - this is where the recipe intentionally goes beyond it.)
LIVING_ROOM_RECIPE = Recipe(
    recipe_id="living_room.standard",
    version="2.0.0",
    room_type="living_room",
    focal_strategy="longest_wall",
    room_goals=["conversation_focus"],
    compose_secondary=True,  # large living rooms get a second seating vignette
    roles=[
        role("primary_seating", "sofa", "focal_wall",
             ["against_wall", "not_block_door"], essential=True),
        role("focal_media", "tv_unit", "opposite_anchor",
             ["against_wall"], depends_on=["primary_seating"]),
        role("floor_anchor", "rug", "front_of_anchor",
             depends_on=["primary_seating"]),
        role("focal_surface", "coffee_table", "front_of_anchor",
             ["min_clearance"], depends_on=["primary_seating", "floor_anchor"]),
        role("support_surface", "side_table", "beside_anchor",
             count=CountRule(mode="fill_available", per_area_m2=14, max=2),
             depends_on=["primary_seating"]),
        role("secondary_seating", "accent_chair", "around_anchor",
             count=CountRule(mode="fill_available", per_area_m2=16, max=2),
             depends_on=["primary_seating"]),
        role("ambient_light", "lighting", "corners",
             count=CountRule(mode="fill_available", per_area_m2=12, max=2),
             depends_on=["primary_seating"]),
        role("storage", "storage", "remaining_wall", ["not_block_door"]),
        role("accent", "decor", "corners",
             count=CountRule(mode="fill_available", per_area_m2=8, max=4)),
    ],
)
