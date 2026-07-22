"""Living-room recipe — mirrors the current LIVING_ROOM_SEQUENCE exactly.

Role order == category order in app/services/guide/flow.py::LIVING_ROOM_SEQUENCE
(sofa, tv_unit, rug, coffee_table, side_table, accent_chair, lighting, storage, decor).
The adapter asserts this equivalence; do not reorder without updating the source.
"""

from spatial_planning.services.recipe.models import CountRule, Recipe
from spatial_planning.services.recipe.recipes import role

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
    roles=[
        role("primary_seating", "sofa", "focal_wall",
             ["against_wall", "not_block_door"], essential=True),
        role("focal_media", "tv_unit", "opposite_anchor",
             ["against_wall"], depends_on=["primary_seating"]),
        role("floor_anchor", "rug", "front_of_anchor",
             depends_on=["primary_seating"]),
        role("focal_surface", "coffee_table", "front_of_anchor",
             ["min_clearance"], depends_on=["primary_seating", "floor_anchor"]),
        # Secondary seating scales with the room: a BIG room gets a perpendicular RETURN sofa
        # forming an L with the primary (until_target lets a second sofa of the same category
        # place; the l_return strategy self-limits to one, and only when the room is large
        # enough for it). A small/normal room gets nothing here and falls through to chairs.
        role("secondary_seating", "sofa", "l_return",
             ["not_block_door"],
             count=CountRule(mode="until_target", metric="seating_capacity", source="pref_or_area_default"),
             depends_on=["primary_seating", "focal_media"]),
        # OPT-IN standalone chaise-lounge (checklist piece 'chaise_lounge', gated off by default).
        # A purposeful lounge piece: it claims space AHEAD of the accessory roles (console / side
        # table / decor, §5 priority) so it's placed after the essentials + core seating but before
        # them. Its own "chaise" role/strategy tucks it into a free corner facing the room; it never
        # competes as a primary/secondary sofa. Skipped (with a notice) when no clean spot survives.
        role("lounge_chaise", "chaise", "chaise",
             ["not_block_door"],
             count=CountRule(mode="single"), store_category="chaise-lounge",
             depends_on=["primary_seating", "secondary_seating"]),
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
        # OPT-IN dining set (checklist piece 'dining_set', gated off by default) — a TABLE in its
        # OWN open pocket BESIDE the conversation group (never overlapping the sofa / rug / coffee /
        # L-return), with dining CHAIRS ringed around it. Declared AFTER the core seating (so the
        # accent-chair seat count is decided WITHOUT counting dining chairs) and before the accessory
        # roles. §5 drop-priority still ranks the set (rank 7) ahead of console / side-table / decor.
        # No separate open area (a tight room) -> the table role places nothing -> a 'didn't fit'
        # notice, and the chairs role finds no table to ring so it places nothing (never orphaned).
        role("dining_table", "dining_table", "dining",
             ["not_block_door"],
             count=CountRule(mode="single"), store_category="dining-table",
             depends_on=["primary_seating", "secondary_seating", "companion_seating"]),
        # Dining chairs: one per ring position around the placed table (per_anchor), each turned to
        # face it. Its own role/strategy (NOT the accent-chair flanking logic); gated by 'dining_set'
        # too (shares the piece via extra_roles) so opting the set out drops the chairs with the table.
        role("dining_seating", "accent_chair", "dining_ring",
             ["not_block_door"],
             count=CountRule(mode="per_anchor", max=6), store_category="chair",
             depends_on=["dining_table"]),
        # ONE side table, placed LAST among the seats so it can be steered to the SAME side as the
        # companion seat (the L-return sofa or accent chair), serving both. Declared here (after the
        # secondary seating + accent chairs) so the declared order is already a valid topo order.
        role("support_surface", "side_table", "beside_anchor",
             count=CountRule(mode="single"),
             depends_on=["primary_seating", "secondary_seating", "companion_seating"]),
        role("ambient_light", "lighting", "corners",
             count=CountRule(mode="fill_available", per_area_m2=12, max=2),
             depends_on=["primary_seating"]),
        # Exactly ONE corner flower-pot-and-plant, even in a large room - several identical plants
        # scattered in every corner reads as repetitive clutter, not decor.
        role("accent", "decor", "corners",
             count=CountRule(mode="single")),
        # Two vases resting ON the console top (on_surface). Its own decor role, so it runs
        # alongside the corner decor (allow_duplicate) and pins to the "vase" store category.
        role("console_accent", "decor", "on_surface",
             count=CountRule(mode="fill_available", per_area_m2=6, max=2),
             depends_on=["storage", "accent"], store_category="vase", allow_duplicate=True),
    ],
)
