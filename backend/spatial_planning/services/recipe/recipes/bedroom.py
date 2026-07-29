"""Bedroom recipe - the first recipe-only room type (no legacy planner branch).

Built entirely from recipe data + reusable strategies/count rules:
  bed against a wall (focal_wall), nightstands mirrored beside it (beside_anchor +
  mirror_pair), wardrobe on a remaining wall, a centred rug, a single reading chair,
  and a table lamp resting ON a nightstand (on_surface). No decor.
"""

from spatial_planning.services.recipe.models import CountRule, Recipe
from spatial_planning.services.recipe.recipes import role

BEDROOM_RECIPE = Recipe(
    recipe_id="bedroom.standard",
    room_type="bedroom",
    focal_strategy="longest_wall",
    room_goals=["restful", "symmetry"],
    roles=[
        role("primary_sleeping", "bed", "focal_wall",
             ["against_wall", "not_block_door"], essential=True),
        role("bedside_support", "side_table", "beside_anchor",
             params={"anchor_category": "bed"},
             count=CountRule(mode="mirror_pair", max=2),
             depends_on=["primary_sleeping"]),
        role("clothing_storage", "storage", "remaining_wall", ["not_block_door"]),
        # A dressing table (vanity) on its OWN clear wall, beside the wardrobe (both are the
        # "storage" role, so allow_duplicate lets it run and store_category pins it to a vanity).
        role("vanity", "storage", "remaining_wall", ["not_block_door"],
             count=CountRule(mode="fill_available", per_area_m2=12, max=1),
             depends_on=["clothing_storage", "primary_sleeping"],
             store_category="dressing-table", allow_duplicate=True),
        role("floor_anchor", "rug", "center_area", ["centered"],
             depends_on=["primary_sleeping"]),  # rug centres on the bed -> bed placed first
        # The reading chair is placed AFTER the wardrobe + dressing table (the essentials), in a
        # clear corner opposite the bed - and skipped if no such clear spot remains.
        role("reading_nook", "accent_chair", "reading_corner",
             depends_on=["primary_sleeping", "clothing_storage", "vanity"]),
        role("bedside_lamp", "lighting", "on_surface",
             count=CountRule(mode="mirror_pair", max=2),
             depends_on=["bedside_support"]),  # a matching table lamp ON each nightstand (a pair)
        # Opt-in plants FILL GENUINELY EMPTY corners (balancing the room). Declared LAST so the
        # reading chair (a seat) gets first pick; plants then soften what remains. The cap allows
        # up to TWO from ~15 m2 up, but the REAL limiter is how many door-free corners are actually
        # clear - so a room with two bare corners gets two, one bare corner gets one.
        role("accent", "decor", "corners",
             count=CountRule(mode="fill_available", per_area_m2=10, max=2),
             depends_on=["primary_sleeping"], store_category="flower-pot-and-plant"),
    ],
)
