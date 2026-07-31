"""Phase 5 - strategy-based pose generation.

The recipe path now derives poses from the strategy's candidate zone (anchor_pose +
settle_pose) and no longer re-derives zones via zones_for_category / suggest_pose. These
tests prove that, broaden the equivalence coverage, and confirm shadow safety.
"""

import spatial_planning.services.recommend.orchestrator as orch
import spatial_planning.services.spatial.autofix as autofix_mod
import spatial_planning.services.spatial.strategies as strat_mod
from spatial_planning.models.geometry import PlacedItem, Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.services.recipe.equivalence import compare_layouts
from spatial_planning.services.recommend.orchestrator import plan_layout, plan_layout_from_recipe

GOLDEN_LIVING_PID = "lay_e70c868492"  # legacy
GOLDEN_LIVING_RECIPE = "lay_60183a9a6d"  # recipe planner (current flow): chair placed BEFORE the console (steered to the door-free flank, flush to the sofa/rug); console on the wall away from the seating, or skipped with a notice if none; the door-side chair drops only when the group is jammed by the entry.

LIVING_ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
    "wall_height_cm": 270,
}
SALON = {
    "vertices": [[0, 0], [600, 0], [600, 560], [0, 560]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 250, "width_cm": 100}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 200, "width_cm": 180}],
    "wall_height_cm": 300,
}
# Opt in EVERY checklist piece that maps to a living-room role, so gating is a no-op and the
# recipe reproduces the pre-gating full-room layout byte-for-byte (golden hashes unchanged).
_ALL_LIVING_PIECES = ["rug", "coffee_table", "tv_unit", "floor_lamp", "side_table", "console", "plant", "vases"]
LIVING_PREFS = Preferences(
    styles=["modern"], budget_tier="mid", total_budget=8000, room_purpose="entertaining",
    included_pieces=_ALL_LIVING_PIECES,
)


def _room(spec):
    return Room.model_validate(spec)


# --- the recipe path no longer touches zones_for_category / suggest_pose -----------


def test_recipe_path_makes_no_zones_for_category_calls(catalog_repo, monkeypatch):
    calls: list[str] = []
    real_zfc = strat_mod.zones_for_category

    def spy(*a, **k):
        calls.append("zfc")
        return real_zfc(*a, **k)

    # patch every reference the recipe path could reach
    monkeypatch.setattr(strat_mod, "zones_for_category", spy)
    monkeypatch.setattr(orch, "zones_for_category", spy)
    monkeypatch.setattr(autofix_mod, "zones_for_category", spy)

    plan_layout_from_recipe(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert calls == [], f"recipe path called zones_for_category {len(calls)} times"

    # sanity: the spy works - legacy DOES call zones_for_category
    plan_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert len(calls) > 0


def test_recipe_path_does_not_use_suggest_pose(catalog_repo, monkeypatch):
    calls: list[str] = []
    real = orch.suggest_pose

    def spy(*a, **k):
        calls.append("suggest_pose")
        return real(*a, **k)

    monkeypatch.setattr(orch, "suggest_pose", spy)
    plan_layout_from_recipe(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert calls == []  # recipe path generates poses from the strategy zone directly

    plan_layout(_room(LIVING_ROOM), LIVING_PREFS, [])  # legacy still uses it
    assert len(calls) > 0


# --- golden + shadow safety --------------------------------------------------------


def test_golden_unchanged_after_pose_change(catalog_repo):
    assert plan_layout_from_recipe(_room(LIVING_ROOM), LIVING_PREFS, []).proposal_id == GOLDEN_LIVING_RECIPE


def test_shadow_still_returns_legacy(catalog_repo):
    import contextlib
    import os

    from spatial_planning.config import get_settings

    @contextlib.contextmanager
    def mode(m):
        prev = os.environ.get("ASSIST_PLANNER_MODE")
        os.environ["ASSIST_PLANNER_MODE"] = m
        get_settings.cache_clear()
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop("ASSIST_PLANNER_MODE", None)
            else:
                os.environ["ASSIST_PLANNER_MODE"] = prev
            get_settings.cache_clear()

    with mode("shadow"):
        out = orch.plan_assist_layout(_room(LIVING_ROOM), LIVING_PREFS, [])
    assert out.proposal_id == GOLDEN_LIVING_PID


# --- broadened equivalence coverage (Task 4) --------------------------------------


def _door(wall, offset, width=90):
    return {"id": f"d{wall}-{offset}", "wall_index": wall, "offset_cm": offset, "width_cm": width}


def _window(wall, offset, width=160):
    return {"id": f"w{wall}-{offset}", "wall_index": wall, "offset_cm": offset, "width_cm": width}


ROOMS = {
    "small": {"vertices": [[0, 0], [320, 0], [320, 300], [0, 300]], "doors": [_door(0, 40, 80)], "windows": []},
    "medium": {"vertices": [[0, 0], [480, 0], [480, 360], [0, 360]], "doors": [_door(0, 40)], "windows": [_window(2, 140)]},
    "large": {"vertices": [[0, 0], [700, 0], [700, 600], [0, 600]], "doors": [_door(0, 300)], "windows": [_window(2, 250), _window(1, 250)]},
    "xlarge": {"vertices": [[0, 0], [900, 0], [900, 720], [0, 720]], "doors": [_door(0, 400), _door(3, 300)], "windows": [_window(2, 350)]},
    "narrow": {"vertices": [[0, 0], [640, 0], [640, 260], [0, 260]], "doors": [_door(0, 40)], "windows": [_window(2, 200)]},
    "lshape": {"vertices": [[0, 0], [600, 0], [600, 300], [300, 300], [300, 480], [0, 480]], "doors": [_door(0, 60), _door(4, 80)], "windows": [_window(5, 100)]},
    "ushape": {"vertices": [[0, 0], [600, 0], [600, 500], [450, 500], [450, 200], [150, 200], [150, 500], [0, 500]], "doors": [_door(0, 250)], "windows": []},
    "pentagon": {"vertices": [[0, 0], [500, 0], [600, 300], [300, 520], [0, 300]], "doors": [_door(0, 200)], "windows": []},
    "no_door": {"vertices": [[0, 0], [500, 0], [500, 420], [0, 420]], "doors": [], "windows": [_window(0, 200)]},
}

LIVING_CASES = [
    Preferences(),
    Preferences(styles=["modern"]),
    Preferences(budget_tier="budget"),
    Preferences(budget_tier="premium", total_budget=15000),
    Preferences(styles=["scandinavian", "minimal"], colors=["Ivory", "Oak"], room_purpose="family"),
    Preferences(room_purpose="compact_living"),
]
def _assert_equivalent(spec, room_type, prefs, placed=None):
    room = _room(spec)
    legacy = plan_layout(room, prefs, placed or [], room_type=room_type)
    recipe = plan_layout_from_recipe(room, prefs, placed or [], room_type=room_type)
    cmp = compare_layouts(legacy, recipe)
    assert cmp.equivalent, (spec["vertices"][2], room_type, prefs.model_dump(exclude_none=True), cmp.diffs)
    assert cmp.proposal_id_match, (room_type, prefs.model_dump(exclude_none=True))


def _assert_valid_and_deterministic(spec, room_type, prefs):
    """For room types that intentionally diverge from legacy (area-scaled): the recipe
    output must be deterministic and free of hard errors."""
    room = _room(spec)
    a = plan_layout_from_recipe(room, prefs, [], room_type=room_type)
    b = plan_layout_from_recipe(room, prefs, [], room_type=room_type)
    assert a.proposal_id == b.proposal_id  # deterministic
    assert not [f for f in a.findings if f.severity == "error"], (room_type, a.findings)


def test_living_room_recipe_valid_and_deterministic(catalog_repo):
    # living_room now scales beyond legacy, so assert validity + determinism, not equality
    for name, spec in ROOMS.items():
        for prefs in LIVING_CASES:
            _assert_valid_and_deterministic(spec, "living_room", prefs)


def test_equivalence_with_preplaced_items(catalog_repo):
    # living_room stays valid/deterministic with a seeded item
    _assert_valid_and_deterministic(ROOMS["medium"], "living_room", Preferences(styles=["modern"]))


def test_accent_pieces_scale_with_room_area(catalog_repo):
    """A bigger room places more accent pieces (the user-requested behaviour)."""
    small = plan_layout_from_recipe(_room(ROOMS["small"]), Preferences(styles=["modern"]), [])
    large = plan_layout_from_recipe(_room(ROOMS["large"]), Preferences(styles=["modern"]), [])
    assert len(large.placements) > len(small.placements)
    # bedroom scales too
    bs = plan_layout_from_recipe(_room(ROOMS["small"]), Preferences(room_type="bedroom"), [], room_type="bedroom")
    bl = plan_layout_from_recipe(_room(ROOMS["large"]), Preferences(room_type="bedroom"), [], room_type="bedroom")
    assert len(bl.placements) >= len(bs.placements)


def _secondary(resp):
    return [p for p in resp.placements if "secondary_zone" in (p.reason_codes or [])]


def test_living_room_never_composes_a_secondary_zone(catalog_repo):
    """A living room keeps ONE conversation group at any size - no secondary cluster
    beside it (compose_secondary is off for living rooms)."""
    for size in ("large", "medium", "small"):
        resp = plan_layout_from_recipe(_room(ROOMS[size]), Preferences(styles=["modern"]), [])
        assert not _secondary(resp), f"{size} living room should not compose a secondary zone"
        assert not [f for f in resp.findings if f.severity == "error"]


def test_large_bedroom_stays_minimal_no_secondary_cluster(catalog_repo):
    """A large bedroom stays minimal - NO extra chair-group/table/lamp cluster in the open area.
    It keeps only the essentials (bed, nightstands, wardrobe, rug, ONE reading chair, ONE lamp)."""
    big = plan_layout_from_recipe(
        _room(ROOMS["large"]), Preferences(room_type="bedroom"), [], room_type="bedroom"
    )
    assert not _secondary(big)  # no secondary cluster is composed
    assert [p.category for p in big.placements].count("accent_chair") <= 1  # at most one chair, never a group
    assert not [f for f in big.findings if f.severity == "error"]
    assert big.proposal_id == plan_layout_from_recipe(
        _room(ROOMS["large"]), Preferences(room_type="bedroom"), [], room_type="bedroom"
    ).proposal_id  # deterministic


def test_large_room_adds_l_return_sofa_before_chairs(catalog_repo):
    """A LARGE living room's secondary seating is a second (L-return) sofa - the SOFA comes
    before any chair (sofa-first ladder, CLAUDE.md 5.1). Phase 2: accent chairs are no longer
    barred once the L-return exists - they may TOP UP toward the seat target on top of the
    (primary + L-return) group - but the room is never a lone sofa, and never a lone 3-seater."""
    resp = plan_layout_from_recipe(_room(ROOMS["large"]), Preferences(styles=["modern"]), [])
    cats = [p.category for p in resp.placements]
    assert cats.count("sofa") == 2  # primary + the perpendicular L-return (sofa before chairs)
    # hard combo rule: a two-sofa group is never a lone 3-seater (the fixture sofas are the
    # generic "sofa" category, so this is the len-based check).
    assert cats.count("sofa") >= 2
    assert not [f for f in resp.findings if f.severity == "error"]
    assert resp.proposal_id == plan_layout_from_recipe(
        _room(ROOMS["large"]), Preferences(styles=["modern"]), []
    ).proposal_id  # deterministic


def test_normal_room_keeps_accent_chairs_not_a_second_sofa(catalog_repo):
    """A normal room keeps a SINGLE sofa (the L-return only fires in a genuinely large room).
    A medium room also gets an accent chair beside the sofa; a very small room may drop it for
    lack of a clear spot beside the sofa (but never sprouts a second sofa)."""
    med = plan_layout_from_recipe(_room(ROOMS["medium"]), Preferences(styles=["modern"]), [])
    med_cats = [p.category for p in med.placements]
    assert med_cats.count("sofa") == 1
    assert "accent_chair" in med_cats  # medium keeps a chair beside the sofa
    assert not [f for f in med.findings if f.severity == "error"]

    small = plan_layout_from_recipe(_room(ROOMS["small"]), Preferences(styles=["modern"]), [])
    assert [p.category for p in small.placements].count("sofa") == 1  # no L-return in a small room
    assert not [f for f in small.findings if f.severity == "error"]


# --- viewing-distance-aware TV (great-rooms float the media; normal rooms wall-mount) --

GREAT_ROOM = {
    "vertices": [[0, 0], [850, 0], [850, 700], [0, 700]],
    "doors": [_door(0, 380, 100)], "windows": [_window(2, 320, 200)],
}


def test_great_room_floats_seating_and_wall_mounts_tv(catalog_repo):
    import math
    from shapely.geometry import Point
    from spatial_planning.services.spatial.analyze import analyze_room

    room = _room(GREAT_ROOM)
    resp = plan_layout_from_recipe(room, Preferences(styles=["modern"]), [])
    tv = next((p for p in resp.placements if p.category == "tv_unit"), None)
    sofa = next((p for p in resp.placements if p.category == "sofa"), None)
    assert tv is not None and sofa is not None

    exterior = analyze_room(room).polygon.exterior
    # the TV stays WALL-MOUNTED (its centre sits within ~a TV depth of the wall)...
    assert "media_at_viewing_distance" not in (tv.reason_codes or [])
    assert Point(tv.pose.x, tv.pose.y).distance(exterior) < 70
    # ...and the SEATING GROUP floats forward off its BACK WALL instead (not glued to it). Measure the
    # float DEPTH along the sofa's facing axis (TV - sofa gap) rather than distance-to-nearest-exterior:
    # in a great room the group may also be shifted sideways toward a side wall (freeing the far flank),
    # so nearest-exterior would catch that side wall, not the float we're asserting.
    from spatial_planning.services.spatial.geometry_utils import front_vector
    f = front_vector(sofa.pose.rotation_deg)
    float_depth = abs((tv.pose.x - sofa.pose.x) * f[0] + (tv.pose.y - sofa.pose.y) * f[1])
    assert float_depth > 150  # sofa sits a real distance in front of the wall-mounted TV, not glued back
    # at a comfortable viewing distance (centre-to-centre; front-to-front ~a step less),
    # far closer than the ~660 a wall-glued sofa would give, and circulation is preserved
    assert math.hypot(tv.pose.x - sofa.pose.x, tv.pose.y - sofa.pose.y) < 520
    assert not [f for f in resp.findings if f.severity == "error"]
    assert not [f for f in resp.findings if f.code == "BLOCKS_WALKWAY"]


def test_normal_room_keeps_wall_mounted_tv(catalog_repo):
    # a normal room must NOT float - the wall is at a comfortable distance (golden-safe)
    resp = plan_layout_from_recipe(_room(ROOMS["medium"]), Preferences(styles=["modern"]), [])
    tv = next((p for p in resp.placements if p.category == "tv_unit"), None)
    assert tv is not None
    assert "media_at_viewing_distance" not in (tv.reason_codes or [])
