"""Phase 1 - checklist gating + didn't-fit notices (living-room "Assist with AI").

Proves each checklist role runs only when its piece is requested, that the essentials-only
default drops the optionals, that a requested-but-unfit piece surfaces an honest notice (and
an excluded piece surfaces none), and that BOTH planner paths (single + templates) gate.
Gating is a pure filter, so the all-opted-in goldens stay byte-identical (see the other
test_recipe_* files); here we assert the NEW gated scenarios.
"""

import contextlib
import os

from spatial_planning.config import get_settings
from spatial_planning.models.geometry import Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.services.recommend.orchestrator import (
    active_roles,
    plan_assist_templates,
    plan_layout_from_recipe,
)
from spatial_planning.services.recipe.registry import get_recipe

# Codes the validation gate must NEVER let through (safety spot-check, requirement 6).
UNSAFE_CODES = {"OVERLAP_ITEM", "OUT_OF_BOUNDS", "BLOCKS_DOOR_SWING", "BLOCKS_WALKWAY"}

LIVING_ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
    "wall_height_cm": 270,
}
TINY = {
    "vertices": [[0, 0], [220, 0], [220, 220], [0, 220]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 20, "width_cm": 80}],
    "windows": [],
}
# A small/medium room (240x330 = 7.9 m^2) with NO clean wall a console can hug: the sofa/TV consume
# the short walls and the side walls have no clear run long enough -> the requested console is
# skipped cleanly (a "didn't fit" notice), even though the recipe path opts small-room consoles in.
NO_CONSOLE_WALL = {
    "vertices": [[0, 0], [240, 0], [240, 330], [0, 330]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 80, "width_cm": 80}],
    "wall_height_cm": 270,
}
ALL_PIECES = ["rug", "coffee_table", "tv_unit", "floor_lamp", "chaise_lounge", "dining_set", "side_table", "console", "plant", "vases"]
OPTIONALS = {"side_table", "console", "plant", "vases"}

# essentials-only default: freshly blessed (a NEW scenario, not a re-bless of an old golden).
GOLDEN_DEFAULT_PID = "lay_ba2a72c11d"  # Phase 2: GAP-driven accent chairs add a 2nd flanking chair toward the seat target


def _room(spec):
    return Room.model_validate(spec)


@contextlib.contextmanager
def planner_mode(mode):
    prev = os.environ.get("ASSIST_PLANNER_MODE")
    os.environ["ASSIST_PLANNER_MODE"] = mode
    get_settings.cache_clear()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("ASSIST_PLANNER_MODE", None)
        else:
            os.environ["ASSIST_PLANNER_MODE"] = prev
        get_settings.cache_clear()


def _cats(resp):
    return {p.category for p in resp.placements}


# --- essentials-only default (included_pieces=None) --------------------------------


def test_essentials_only_default_drops_optionals(catalog_repo):
    resp = plan_layout_from_recipe(_room(LIVING_ROOM), Preferences(styles=["modern"]), [])
    cats = _cats(resp)
    # core seating + all four essentials are present...
    assert "sofa" in cats
    assert {"rug", "coffee_table", "tv_unit", "lighting"} <= cats  # lighting == floor_lamp role
    assert "accent_chair" in cats  # core companion seating still runs
    # ...and NONE of the optionals (console/side_table/plant/vases) appear
    assert "storage" not in cats  # console
    assert "side_table" not in cats
    assert "decor" not in cats  # plant + vases (both the 'decor' category)
    # a freshly-blessed, deterministic proposal id for this new default scenario
    assert resp.proposal_id == GOLDEN_DEFAULT_PID
    assert resp.proposal_id == plan_layout_from_recipe(_room(LIVING_ROOM), Preferences(styles=["modern"]), []).proposal_id
    assert resp.notices == []  # nothing was requested-but-unfit
    assert not [f for f in resp.findings if f.severity == "error"]


# --- unchecking a piece removes exactly that piece ---------------------------------


def test_unchecking_tv_removes_tv(catalog_repo):
    incl = ["rug", "coffee_table", "floor_lamp"]  # tv_unit omitted
    resp = plan_layout_from_recipe(_room(LIVING_ROOM), Preferences(styles=["modern"], included_pieces=incl), [])
    assert "tv_unit" not in _cats(resp)
    # the still-checked essentials remain
    assert {"rug", "coffee_table", "lighting"} <= _cats(resp)


# --- didn't-fit notice for a requested piece, and silence for an excluded one ------


def test_requested_but_unfit_piece_emits_notice(catalog_repo):
    # The 480x360 room is small/medium and requests the (oversized) chaise + dining set; neither
    # physically fits -> an honest "didn't fit" notice for each. (The console DOES fit here now -
    # see test_console_placed_in_small_room_with_clean_wall - so it is NOT among the notices.)
    resp = plan_layout_from_recipe(
        _room(LIVING_ROOM), Preferences(styles=["modern"], included_pieces=ALL_PIECES), []
    )
    assert "The chaise lounge didn't fit this room." in resp.notices
    assert "The dining set didn't fit this room." in resp.notices
    assert "The console didn't fit this room." not in resp.notices


def test_console_placed_in_small_room_with_clean_wall(catalog_repo):
    # NEW console rule: on the recipe path a small/medium room no longer blanket-skips the console.
    # The 480x360 room has a clean secondary wall (the east wall: not the TV/door/window wall, no
    # sofa in its band), so an opted-in console is PLACED there - no "didn't fit" notice, no skip.
    resp = plan_layout_from_recipe(
        _room(LIVING_ROOM), Preferences(styles=["modern"], included_pieces=["rug", "coffee_table", "tv_unit", "console"]), []
    )
    assert "storage" in _cats(resp)  # the console is placed
    assert not any("console" in n for n in resp.notices)
    assert not [s for s in resp.skipped if s.category == "storage" and s.reason == "did_not_fit"]
    assert not [f for f in resp.findings if f.severity == "error"]  # placed cleanly (clean wall)


def test_console_without_clean_wall_skipped_with_notice(catalog_repo):
    # Same recipe path, but NO_CONSOLE_WALL has no clean wall long enough for a console -> even
    # though it is opted in, physical fit governs: the console is skipped cleanly with the honest
    # "didn't fit" notice + a did_not_fit skip, and the rest of the room still lays out.
    resp = plan_layout_from_recipe(
        _room(NO_CONSOLE_WALL), Preferences(styles=["modern"], included_pieces=["rug", "coffee_table", "tv_unit", "console"]), []
    )
    assert "storage" not in _cats(resp)  # no console placed
    assert "The console didn't fit this room." in resp.notices
    console_skips = [s for s in resp.skipped if s.category == "storage"]
    assert console_skips and console_skips[0].reason == "did_not_fit"
    assert not [f for f in resp.findings if f.severity == "error"]


def test_excluded_piece_emits_no_notice(catalog_repo):
    # Same room, but the console is NOT requested -> it simply doesn't run: no placement, no
    # notice, and no skip carrying the did_not_fit reason.
    resp = plan_layout_from_recipe(
        _room(LIVING_ROOM), Preferences(styles=["modern"], included_pieces=["rug", "coffee_table"]), []
    )
    assert not any("console" in n for n in resp.notices)
    assert "storage" not in _cats(resp)
    assert not [s for s in resp.skipped if s.category == "storage" and s.reason == "did_not_fit"]


# --- pathological gating: dependency filtered out must not crash --------------------


def test_essential_excluded_optional_included_plans_cleanly(catalog_repo):
    # included=["console"] excludes even the rug essential; companion_seating depends_on
    # storage, focal_surface depends_on floor_anchor -> filtering must not raise, and the
    # gate must keep the layout clean.
    resp = plan_layout_from_recipe(
        _room(LIVING_ROOM), Preferences(styles=["modern"], included_pieces=["console"]), []
    )
    cats = _cats(resp)
    assert "sofa" in cats  # core seating always runs
    assert "rug" not in cats and "tv_unit" not in cats  # essentials excluded
    assert not [f for f in resp.findings if f.severity == "error"]


# --- both paths gate: templates respect included_pieces ----------------------------


def test_templates_path_gates_too(catalog_repo):
    incl = ["rug", "coffee_table", "floor_lamp"]  # tv_unit + all optionals excluded
    with planner_mode("recipe"):
        tpls = plan_assist_templates(_room(LIVING_ROOM), Preferences(styles=["modern"], included_pieces=incl), [])
    assert tpls
    for _label, _recommended, resp in tpls:
        cats = _cats(resp)
        assert "tv_unit" not in cats
        assert not (OPTIONALS & cats)  # no console/side_table/plant/vases in any template


# --- the gating helper is what both paths use --------------------------------------


def test_active_roles_helper_filters_by_active_set(catalog_repo):
    recipe = get_recipe("living_room")
    # default -> essentials + core only (no optional roles)
    default_roles = {r.role for r in active_roles(recipe, Preferences(), "living_room")}
    assert "storage" not in default_roles and "support_surface" not in default_roles
    assert "primary_seating" in default_roles  # core
    assert "secondary_seating" in default_roles  # core (no checklist piece maps to it)
    assert "companion_seating" in default_roles  # core
    assert "ambient_light" in default_roles  # floor_lamp essential
    # opt in everything -> every role returns
    all_roles = {r.role for r in active_roles(recipe, Preferences(included_pieces=ALL_PIECES), "living_room")}
    assert all_roles == {r.role for r in recipe.roles}
    # the bedroom is ALSO gated now (it has its own piece table): the default keeps the
    # bed (core) + the essential roles, and drops the optional dressing-table / reading-chair.
    br = get_recipe("bedroom")
    bedroom_default = {r.role for r in active_roles(br, Preferences(room_type="bedroom"), "bedroom")}
    assert "primary_sleeping" in bedroom_default  # core (bed) always
    assert "bedside_support" in bedroom_default  # nightstands (essential)
    assert "clothing_storage" in bedroom_default  # wardrobe (essential)
    assert "floor_anchor" in bedroom_default  # rug (essential)
    assert "vanity" not in bedroom_default  # dressing table (optional) -> off by default
    assert "reading_nook" not in bedroom_default  # reading chair (optional) -> off by default
    # opting the optionals in returns their roles too
    bedroom_all = {
        r.role
        for r in active_roles(
            br,
            Preferences(
                room_type="bedroom",
                included_pieces=["nightstands", "wardrobe", "rug", "bedside_lamp", "dressing_table", "reading_chair"],
            ),
            "bedroom",
        )
    }
    assert "vanity" in bedroom_all and "reading_nook" in bedroom_all
    # a room type WITHOUT a piece table is still never gated
    assert active_roles(recipe, Preferences(included_pieces=[]), "office") == list(recipe.roles)


# --- safety: gating never weakens the validation gate ------------------------------


def test_gating_keeps_every_layout_safe(catalog_repo):
    scenarios = [
        Preferences(styles=["modern"]),  # default
        Preferences(styles=["modern"], included_pieces=ALL_PIECES),  # all-in
        Preferences(styles=["modern"], included_pieces=["rug", "coffee_table", "floor_lamp"]),  # TV off
    ]
    for prefs in scenarios:
        for spec in (LIVING_ROOM, TINY):
            resp = plan_layout_from_recipe(_room(spec), prefs, [])
            bad = [f for f in resp.findings if f.code in UNSAFE_CODES]
            assert not bad, (spec["vertices"][2], prefs.model_dump(exclude_none=True), bad)
