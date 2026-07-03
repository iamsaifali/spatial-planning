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
    # No secondary seating vignette: a large living room keeps ONE conversation group
    # (the open floor behind the floated seating stays open) rather than sprouting a second
    # cluster of chairs/table/lamp beside it.
    compose_secondary=False,
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
             count=CountRule(mode="single"),  # a living room gets ONE side table, not a pair
             depends_on=["primary_seating"]),
        # Secondary seating scales with the room: a BIG room gets a perpendicular RETURN sofa
        # forming an L with the primary (until_target lets a second sofa of the same category
        # place; the l_return strategy self-limits to one, and only when the room is large
        # enough for it). A small/normal room gets nothing here and falls through to chairs.
        role("secondary_seating", "sofa", "l_return",
             ["not_block_door"],
             count=CountRule(mode="until_target", metric="seating_capacity", source="pref_or_area_default"),
             depends_on=["primary_seating", "focal_media"]),
        # Storage goes BEFORE the accent chairs so the chairs can balance to the OPPOSITE side
        # (and storage avoids the TV wall). depends on focal_media so the TV wall is known.
        role("storage", "storage", "remaining_wall", ["not_block_door"],
             depends_on=["primary_seating", "focal_media"]),
        # Fallback conversation seating: a pair of accent chairs around the sofa. around_anchor
        # skips these once an L-return sofa exists (a room gets the second sofa OR the chairs),
        # and steers them to the side away from the storage.
        role("companion_seating", "accent_chair", "around_anchor",
             count=CountRule(mode="fill_available", per_area_m2=16, max=2),
             depends_on=["primary_seating", "secondary_seating", "storage"]),
        role("ambient_light", "lighting", "corners",
             count=CountRule(mode="fill_available", per_area_m2=12, max=2),
             depends_on=["primary_seating"]),
        role("accent", "decor", "corners",
             count=CountRule(mode="fill_available", per_area_m2=8, max=4)),
    ],
)
