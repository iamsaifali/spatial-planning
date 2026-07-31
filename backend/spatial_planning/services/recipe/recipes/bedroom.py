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
        # Opt-in LOUNGE sofa: a compact sofa (the selector best-fits it from sofa / 2-/3-seater) hugging
        # a SIDE wall near the bed's TOE, facing into the room - the seat of a small sitting area. Placed
        # BEFORE the work nook (user: the sofa/centre-table and the office nook are SWAPPED - the sofa now
        # gets first pick of a toe-side wall, and the desk takes the OTHER side). Skipped (a 'didn't fit'
        # notice, taking the centre table with it) when no side wall has a clear run past the bed's foot.
        role("lounge_sofa", "sofa", "lounge_seat", ["against_wall", "not_block_door"],
             depends_on=["primary_sleeping", "clothing_storage"]),
        # The lounge's CENTRE table, pulled up in front of the lounge sofa. Requires the sofa (depends on
        # lounge_sofa): if the sofa didn't fit, the table is skipped too (never marooned in the room).
        role("lounge_center", "coffee_table", "lounge_table", ["centered"],
             depends_on=["lounge_sofa"], store_category="center-table"),
        # A FLOOR LAMP (floor-stand) beside the lounge sofa's arm, completing the sitting area. Comes with
        # the sofa (gated by the same checklist key via extra_roles). allow_duplicate since the `lighting`
        # group may already be placed (bedside lamps / the corner floor lamp); this is a SECOND floor-stand.
        role("lounge_light", "lighting", "lounge_light",
             depends_on=["lounge_sofa"], store_category="floor-stand", allow_duplicate=True),
        # The work nook: a DESK on a clear wall (away from the bed / wardrobe / the lounge sofa - the few
        # clear bedroom walls compete), placed AFTER the lounge sofa so the sofa owns its toe-side wall and
        # the desk takes the OTHER side (the swap). Placed BEFORE the dressing table so the desk OWNS its
        # wall over the vanity. Opt-in; its chair is added by `work_seat` below.
        role("work_nook", "desk", "work_desk", ["not_block_door"],
             depends_on=["primary_sleeping", "clothing_storage", "lounge_sofa"],
             store_category="office-table"),
        # A dressing table (vanity) on its OWN clear wall, beside the wardrobe (both are the "storage"
        # role, so allow_duplicate lets it run and store_category pins it to a vanity). Placed AFTER the
        # work nook and never on the desk's wall -> in a tight room it yields to the desk (skipped).
        role("vanity", "storage", "remaining_wall", ["not_block_door"],
             count=CountRule(mode="fill_available", per_area_m2=12, max=1),
             depends_on=["clothing_storage", "primary_sleeping", "work_nook"],
             store_category="dressing-table", allow_duplicate=True),
        # The TV unit on the wall the bed FACES (opposite the headboard), watchable from bed. Placed
        # AFTER the wall pieces (wardrobe / desk / dresser claim walls first) - if the facing wall is
        # taken or blocked, the TV yields (skipped), per the bedroom drop priority. Opt-in.
        role("media", "tv_unit", "bed_media", ["not_block_door"],
             depends_on=["primary_sleeping", "clothing_storage", "work_nook", "vanity"],
             store_category="tv-table"),
        role("floor_anchor", "rug", "center_area", ["centered"],
             depends_on=["primary_sleeping"]),  # rug centres on the bed -> bed placed first
        # The reading chair is placed AFTER the wardrobe + dressing table (the essentials), in a
        # clear corner opposite the bed - and skipped if no such clear spot remains.
        role("reading_nook", "accent_chair", "reading_corner",
             depends_on=["primary_sleeping", "clothing_storage", "vanity"]),
        # The work-nook CHAIR: an OFFICE chair pulled up in front of the desk, facing it. Declared AFTER
        # reading_nook (so the reading / vanity chair claims its spot first) with allow_duplicate, since
        # both are the accent_chair role. store_category pins it to an office chair, not a lounge chair.
        role("work_seat", "accent_chair", "desk_seat",
             depends_on=["work_nook"],
             store_category="office-chair", allow_duplicate=True),
        # The dressing table's STOOL: a small chair pulled up in front of the vanity, facing it - comes
        # WITH the dressing table (gated by the same checklist key via extra_roles). allow_duplicate since
        # the reading/work chairs already placed the accent_chair group; declared AFTER them so they claim
        # their spots first. Dropped (vanity kept, chair-less) if it would block a walkway or crowd the bed.
        role("vanity_seat", "accent_chair", "vanity_seat",
             depends_on=["vanity"], allow_duplicate=True),
        # A matching table lamp ON each nightstand (a pair). allow_duplicate so it's NEVER skipped for
        # "lighting already placed": the bedside lampshades are a distinct, essential instance, independent
        # of the corner / lounge FLOOR-stands - one of which may now claim the `lighting` group first
        # (the lounge floor lamp is placed before this role, beside the sofa).
        role("bedside_lamp", "lighting", "on_surface",
             count=CountRule(mode="mirror_pair", max=2),
             depends_on=["bedside_support"], allow_duplicate=True),
        # Opt-in FLOOR LAMP: a floor-stand in a clear corner (ambient light for the reading nook / room).
        # store_category pins it to a floor-stand (not the bedside lampshade); allow_duplicate lets it run
        # even though the bedside lamps already placed the `lighting` group. Declared BEFORE the plant so
        # the lamp claims a corner first; the plant then fills a remaining one.
        role("floor_light", "lighting", "corners",
             count=CountRule(mode="single"),
             depends_on=["primary_sleeping"], store_category="floor-stand", allow_duplicate=True),
        # Opt-in plant: ONE floor plant in a genuinely empty corner (capped to a single one - two read
        # cluttered). Declared LAST so the reading chair + floor lamp claim corners first; the plant
        # softens what remains, and is skipped when no bare corner is left.
        role("accent", "decor", "corners",
             count=CountRule(mode="fill_available", per_area_m2=10, max=1),
             depends_on=["primary_sleeping"], store_category="flower-pot-and-plant"),
    ],
)
