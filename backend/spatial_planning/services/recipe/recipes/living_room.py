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
        # The coffee table anchors to the SOFA FRONT (not the rug), so it no longer depends on the rug -
        # this frees the rug to be placed LATER (after the whole seating group exists) without dragging
        # the coffee table with it. The rug is walkable, so moving it later changes ONLY the rug's own
        # size/position; every other piece is placed identically (nothing treats a rug as a blocker).
        role("focal_surface", "coffee_table", "front_of_anchor",
             ["min_clearance"], depends_on=["primary_seating"]),
        # Secondary seating scales with the room, via the living-room `_execute_secondary_sofa` fill
        # ladder (NOT the generic until_target loop). AUTO (no explicit seat count): today's backbone -
        # a single 2-seater RETURN sofa forming an L (large rooms only; small/normal rooms get nothing
        # and fall through to chairs). EXPLICIT seat count (Q1): gap-sized returns (3-seater vs 2-seater)
        # on BOTH flanks up to MAX_RETURN_SOFAS, forming a U to reach the requested count - a leftover
        # +1 is left to a chair. The l_return strategy sizes the return zone to `return_category`.
        role("secondary_seating", "sofa", "l_return",
             ["not_block_door"],
             count=CountRule(mode="until_target", metric="seating_capacity", source="pref_or_area_default"),
             depends_on=["primary_seating", "focal_media"]),
        # Conversation seating: a pair of accent chairs around the sofa. around_anchor skips these
        # once an L-return sofa exists (a room gets the second sofa OR the chairs). Placed BEFORE the
        # console (seating outranks storage): the chair claims the door-FREE flank first, then the
        # console takes the remaining wall away from the seating group (see `storage` below).
        role("companion_seating", "accent_chair", "around_anchor",
             count=CountRule(mode="fill_available", per_area_m2=16, max=2),
             depends_on=["primary_seating", "secondary_seating"]),
        # The RUG runs here - AFTER the whole conversation group is placed (primary + L-return/U + flanking
        # chairs) - so it can size itself to the ENTIRE group ("front legs on": the front legs of every
        # seating piece rest on the rug, back legs off), not just the primary sofa. Dining chairs are not
        # placed yet, so the accent chairs it sees are only the flanking (conversation) ones. Walkable, so
        # placing it now doesn't perturb any other piece.
        role("floor_anchor", "rug", "front_of_anchor",
             depends_on=["primary_seating", "secondary_seating", "companion_seating"]),
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
        # Storage (console) runs AFTER the dining set (dining_table priority > console): the DINING claims
        # its open floor block FIRST, so the console never eats the area the dining needs (it used to be
        # placed before the dining and blocked it). The console then steers to a clear NON-TV wall away from
        # the seating group (depends on focal_media for the TV wall, companion_seating for the seat flank).
        role("storage", "storage", "remaining_wall", ["not_block_door"],
             depends_on=["primary_seating", "focal_media", "companion_seating", "dining_table"]),
        # OPT-IN standalone chaise-lounge (checklist piece 'chaise_lounge', gated off by default). Placed
        # AFTER the dining set so, when BOTH are opted in, the DINING claims its freed block first and the
        # chaise then routes around it (dining is a circulation blocker) - both fit in a big room instead
        # of competing. Its own "chaise" role/strategy hugs a clear SECONDARY wall facing the room (never
        # behind the group), keeping a circulation walkway off every placed piece; it never competes as a
        # primary/secondary sofa. In a genuinely tight room it yields (skipped with a notice) - the chaise
        # is the most optional lounge piece, so it gives way to the dining set the user also asked for.
        role("lounge_chaise", "chaise", "chaise",
             ["not_block_door"],
             count=CountRule(mode="single"), store_category="chaise-lounge",
             depends_on=["primary_seating", "secondary_seating", "companion_seating"]),
        # SECOND rug that anchors the reading NOOK under the chaise - a MASSIVE room (>= 60 m2) reads as several
        # tight rug-anchored clusters, not one group in a void. Runs after the chaise (its zone strategy self-
        # gates on room area + the chaise being placed) and pins the "carpet" store category; allow_duplicate
        # because a rug is already placed. Smaller than the main rug (sized to the chaise) so the two coordinate
        # rather than match. Places nothing in <60 m2 rooms or when the chaise didn't land - no notice, no golden
        # churn. Walkable, so it perturbs no other piece.
        role("nook_rug", "rug", "nook_rug",
             count=CountRule(mode="single"), store_category="carpet",
             depends_on=["lounge_chaise"], allow_duplicate=True),
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
        # The reading-nook satellites run LAST (after the regular side table + lamps have claimed their spots by
        # the seating, so those are never preempted): a SIDE TABLE then a FLOOR LAMP tucked beside the chaise,
        # completing the vignette (chaise + nook rug + side table + lamp = one tight cluster). Massive rooms
        # only, chaise placed (the strategy self-gates); side table first so the lamp avoids it; allow_duplicate
        # since a side table / lamp is already placed elsewhere. No clear spot beside the chaise -> nothing.
        role("nook_side_table", "side_table", "nook_satellite",
             count=CountRule(mode="single"), store_category="service-table",
             depends_on=["nook_rug", "support_surface"], allow_duplicate=True),
        role("nook_light", "lighting", "nook_satellite",
             count=CountRule(mode="single"), store_category="floor-stand",
             depends_on=["nook_side_table", "ambient_light"], allow_duplicate=True),
    ],
)
