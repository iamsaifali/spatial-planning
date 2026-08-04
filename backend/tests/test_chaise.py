"""Phase 3a — standalone chaise-lounge (living-room "Assist with AI").

The chaise-lounge is a STANDALONE lounge piece, opt-in via the checklist (`chaise_lounge`),
placed WALL-HUGGING: its back against a clear secondary wall, long side PARALLEL to that wall,
facing into the room (the way a sofa / console hugs a wall — NOT angled in a corner). It must:
  * sit ALONG A WALL (back to a clear wall, parallel), never a corner diagonal,
  * NEVER compete as a primary/secondary sofa (its own "chaise" placement role — the remap),
  * be OFF by default (the essentials-only default is byte-identical),
  * route every placement through the validation gate (always safe),
  * skip cleanly with a "didn't fit" notice when no clean spot survives.

These tests use a deterministic test-local catalog: the fixture catalog plus a SINGLE
chaise-lounge product, so the selector's choice is fixed.
"""

import json
import math

import pytest

from spatial_planning.config import get_settings
from spatial_planning.models.geometry import Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import placement_group
from spatial_planning.services.catalog import CatalogRepository, set_repository
from spatial_planning.services.recommend.orchestrator import plan_layout_from_recipe
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.geometry_utils import front_vector, rotation_for_normal

# Codes the validation gate must NEVER let through (safety spot-check).
UNSAFE_CODES = {"OVERLAP_ITEM", "OUT_OF_BOUNDS", "BLOCKS_DOOR_SWING", "BLOCKS_WALKWAY"}

# A large living room with a genuinely empty corner (matches CLAUDE.md's repro room).
BIG_LIVING = {
    "vertices": [[0, 0], [600, 0], [600, 520], [0, 520]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 85}],
    "windows": [],
    "wall_height_cm": 270,
}
# A wide great-room that reliably yields an L-shaped seating group (primary sofa + a FLOATED
# L-return whose back faces a side wall) with room to spare beyond the L-return on that wall - so a
# chaise could (before the fix) land on the L-return's wall, BEHIND the seating.
WIDE_L = {
    "vertices": [[0, 0], [720, 0], [720, 480], [0, 480]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90}],
    "windows": [],
    "wall_height_cm": 270,
}
# The 480x360 room + Preferences(styles=["modern"]) essentials-only default golden (Phase 2).
LIVING_ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
    "wall_height_cm": 270,
}
TINY = {  # too cramped for a standalone chaise: no 150cm-clear corner survives
    "vertices": [[0, 0], [180, 0], [180, 180], [0, 180]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 20, "width_cm": 80}],
    "windows": [],
}
GOLDEN_DEFAULT_PID = "lay_ba2a72c11d"  # essentials-only default (unchanged by the opt-in chaise)

_CHAISE_PRODUCT = {
    "id": "chaise-test-001",
    "name": "Test Chaise Lounge",
    "category": "chaise-lounge",
    "price": 720,
    "width_cm": 145,
    "depth_cm": 78,
    "height_cm": 82,
    "style_tags": ["modern"],
    "colors": ["Grey"],
    "image_url": "",
    "is_walkable": False,
    "shape": "rect",
    "room_types": ["living_room"],
    "seating_capacity": 1,
}


def _room(spec):
    return Room.model_validate(spec)


def _prefs(pieces=None):
    return Preferences(styles=["modern"], included_pieces=pieces)


@pytest.fixture()
def chaise_repo(tmp_path):
    """The fixture catalog PLUS one chaise-lounge product — deterministic, and the only
    chaise the selector can choose. Installed as the active repository for the test."""
    settings = get_settings()
    base = json.loads((settings.resolve("spatial_planning/data/catalog.json")).read_text())
    catalog = base + [dict(_CHAISE_PRODUCT)]
    path = tmp_path / "catalog_with_chaise.json"
    path.write_text(json.dumps(catalog))
    repo = CatalogRepository.load(path, settings.resolve(settings.static_dir))
    set_repository(repo)
    return repo


def _cats(resp):
    return {p.category for p in resp.placements}


def _along_wall(spec, placement, back_tol_cm=18.0, angle_tol_deg=8.0):
    """Verify a placement sits ALONG A WALL (back against a clear wall, long side parallel, facing
    into the room) rather than angled in a corner. Returns (wall_index, back_gap_cm, angle_err_deg).

    The chaise faces into the room, so the wall it hugs is the one whose inward normal best matches
    the chaise's front vector. Two independent checks capture "along a wall, not a corner":
      * ROTATION aligns with that wall — the chaise's rotation equals rotation_for_normal(wall.normal)
        (i.e. its long side is parallel to the wall and it faces off it into the room), and
      * its BACK EDGE is right at the wall — the back-centre point is within a few cm of the wall
        line (a corner-diagonal piece would be angled ~45° off every wall and float off the line).
    """
    analysis = analyze_room(_room(spec))
    x, y, rot = placement.pose.x, placement.pose.y, placement.pose.rotation_deg
    f = front_vector(rot)
    # the wall the piece faces / backs onto = the one whose inward normal aligns with the front vector
    wi = max(range(len(analysis.walls)), key=lambda i: (f[0] * analysis.walls[i].normal[0] + f[1] * analysis.walls[i].normal[1]))
    wall = analysis.walls[wi]
    # rotation parallel to + facing off this wall
    expected_rot = rotation_for_normal(wall.normal)
    angle_err = abs((rot - expected_rot + 180.0) % 360.0 - 180.0)
    assert angle_err <= angle_tol_deg, (f"chaise rot {rot} not parallel to wall {wi} (expected {expected_rot})")
    # back-centre point sits right on the wall line (distance along the inward normal ~ 0)
    back_cx = x - f[0] * placement.product.depth_cm / 2.0
    back_cy = y - f[1] * placement.product.depth_cm / 2.0
    back_gap = (back_cx - wall.start[0]) * wall.normal[0] + (back_cy - wall.start[1]) * wall.normal[1]
    assert abs(back_gap) <= back_tol_cm, (f"chaise back not against wall {wi}: gap {back_gap:.1f}cm")
    return wi, back_gap, angle_err


# --- 1. chaise places when opted in, valid, and is NOT a sofa ----------------------


def test_chaise_places_when_opted_in(chaise_repo):
    resp = plan_layout_from_recipe(
        _room(BIG_LIVING), _prefs(["rug", "coffee_table", "tv_unit", "floor_lamp", "chaise_lounge"]), []
    )
    chaises = [p for p in resp.placements if p.category == "chaise"]
    assert len(chaises) == 1, resp.notices
    ch = chaises[0]
    # correct role + store category
    assert ch.category == "chaise"
    assert ch.product.category == "chaise-lounge"
    assert ch.product.id == "chaise-test-001"
    # placed validly — no unsafe finding anywhere in the layout
    assert not [f for f in resp.findings if f.code in UNSAFE_CODES]
    assert not [f for f in resp.findings if f.severity == "error"]
    # it is NOT in the sofa role: the chaise's placement group is its own "chaise", not "sofa"
    assert placement_group(ch.product.category) == "chaise"
    assert ch.category != "sofa"


# --- 1b. chaise sits ALONG A WALL (back to wall, parallel), not angled in a corner ---


def test_chaise_hugs_a_wall(chaise_repo):
    resp = plan_layout_from_recipe(
        _room(BIG_LIVING), _prefs(["rug", "coffee_table", "tv_unit", "floor_lamp", "chaise_lounge"]), []
    )
    ch = next(p for p in resp.placements if p.category == "chaise")
    # rotation is an axis-aligned wall orientation (0/90/180/270 in a rectangular room), NOT a corner
    # diagonal (~45°): a corner-tucked piece would be angled off every wall.
    assert min((ch.pose.rotation_deg % 90.0), 90.0 - (ch.pose.rotation_deg % 90.0)) <= 8.0
    # and its back edge is right against a clear wall, long side parallel to it, facing into the room
    wi, back_gap, angle_err = _along_wall(BIG_LIVING, ch)
    # it hugs a SECONDARY wall — not the wall the primary sofa hugs
    sofa = next(p for p in resp.placements if p.category == "sofa")
    sofa_wall = max(
        range(len(analyze_room(_room(BIG_LIVING)).walls)),
        key=lambda i: (
            front_vector(sofa.pose.rotation_deg)[0] * analyze_room(_room(BIG_LIVING)).walls[i].normal[0]
            + front_vector(sofa.pose.rotation_deg)[1] * analyze_room(_room(BIG_LIVING)).walls[i].normal[1]
        ),
    )
    assert wi != sofa_wall, "chaise must not share the primary sofa's wall"


def _back_wall(analysis, placement):
    """The wall a placement BACKS ONTO = the one whose inward normal best aligns with its front
    vector (equivalently, the wall its back edge faces) - the wall BEHIND the piece."""
    f = front_vector(placement.pose.rotation_deg)
    return max(
        range(len(analysis.walls)),
        key=lambda i: f[0] * analysis.walls[i].normal[0] + f[1] * analysis.walls[i].normal[1],
    )


# --- 1c. in an L-shaped group the chaise never lands on a wall BEHIND the seating ---


def test_chaise_not_behind_L_group(chaise_repo):
    """An L-group backs onto TWO walls (the primary sofa's wall AND the L-return's wall). The chaise
    must hug a genuinely clear wall BESIDE or ACROSS FROM the seating - never behind ANY seating
    piece (primary OR L-return), even when the L-return FLOATS off its wall with room to spare."""
    resp = plan_layout_from_recipe(
        _room(WIDE_L), _prefs(["rug", "coffee_table", "tv_unit", "floor_lamp", "chaise_lounge"]), []
    )
    analysis = analyze_room(_room(WIDE_L))
    sofas = [p for p in resp.placements if p.category == "sofa"]
    assert len(sofas) >= 2, f"expected a primary + L-return, got {len(sofas)} sofa(s)"
    ch = next(p for p in resp.placements if p.category == "chaise")

    # the wall the chaise hugs (the one its front faces off / its back is against)
    ch_wall = _back_wall(analysis, ch)
    # the walls BEHIND the seating group: every placed sofa's back wall (primary + L-return)
    seating_back_walls = {_back_wall(analysis, s) for s in sofas}
    assert ch_wall not in seating_back_walls, (
        f"chaise wall {ch_wall} sits behind a seating piece (seating backs onto {sorted(seating_back_walls)})"
    )
    # also not the TV wall
    tv = next((p for p in resp.placements if p.category == "tv_unit"), None)
    if tv is not None:
        assert ch_wall != _back_wall(analysis, tv), "chaise must not share the TV wall"
    # still safe
    assert not [f for f in resp.findings if f.code in UNSAFE_CODES]
    assert not [f for f in resp.findings if f.severity == "error"]


# --- 2. off by default; essentials-only default PID unchanged ----------------------


def test_default_has_no_chaise_and_pid_unchanged(catalog_repo):
    # essentials-only default (included_pieces=None) never runs the chaise role.
    resp = plan_layout_from_recipe(_room(LIVING_ROOM), _prefs(None), [])
    assert "chaise" not in _cats(resp)
    assert resp.proposal_id == GOLDEN_DEFAULT_PID  # byte-identical to the pre-chaise default


def test_default_has_no_chaise_even_with_chaise_in_catalog(chaise_repo):
    # A chaise product is available, but the default doesn't opt it in -> no chaise, no notice.
    resp = plan_layout_from_recipe(_room(BIG_LIVING), _prefs(None), [])
    assert "chaise" not in _cats(resp)
    assert not any("chaise" in n.lower() for n in resp.notices)


# --- 3. cramped room: chaise skipped + honest "didn't fit" notice ------------------


def test_tiny_room_chaise_skipped_with_notice(chaise_repo):
    resp = plan_layout_from_recipe(_room(TINY), _prefs(["chaise_lounge"]), [])
    assert "chaise" not in _cats(resp)  # no clean corner -> skipped, not crammed
    assert "The chaise lounge didn't fit this room." in resp.notices
    assert not [f for f in resp.findings if f.code in UNSAFE_CODES]


# --- 4. remap proof: a chaise is never selected for the sofa role ------------------


def test_chaise_never_selected_as_sofa(chaise_repo):
    # Opt in the chaise AND plan a normal living room: every sofa-role placement must be a real
    # sofa store category, never the chaise-lounge (the remap makes the sofa group exclude it).
    resp = plan_layout_from_recipe(
        _room(BIG_LIVING), _prefs(["rug", "coffee_table", "tv_unit", "floor_lamp", "chaise_lounge"]), []
    )
    sofas = [p for p in resp.placements if p.category == "sofa"]
    assert sofas  # the room is furnished with real sofas
    for s in sofas:
        assert s.product.category != "chaise-lounge"
        assert placement_group(s.product.category) == "sofa"


# --- 5. safety sweep: every opted-in chaise layout is gate-clean --------------------


def test_chaise_safety_sweep(chaise_repo):
    rooms = [
        BIG_LIVING,
        LIVING_ROOM,
        TINY,
        {  # door on a side wall + a window
            "vertices": [[0, 0], [520, 0], [520, 440], [0, 440]],
            "doors": [{"id": "d1", "wall_index": 1, "offset_cm": 60, "width_cm": 90}],
            "windows": [{"id": "w1", "wall_index": 0, "offset_cm": 180, "width_cm": 160}],
        },
        {  # two doors
            "vertices": [[0, 0], [560, 0], [560, 480], [0, 480]],
            "doors": [
                {"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90},
                {"id": "d2", "wall_index": 3, "offset_cm": 60, "width_cm": 85},
            ],
            "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 200, "width_cm": 200}],
        },
    ]
    incl = ["rug", "coffee_table", "tv_unit", "floor_lamp", "chaise_lounge", "side_table", "console", "plant", "vases"]
    checked = 0
    for spec in rooms:
        resp = plan_layout_from_recipe(_room(spec), _prefs(incl), [])
        bad = [f for f in resp.findings if f.code in UNSAFE_CODES]
        assert not bad, (spec["vertices"][2], bad)
        checked += 1
    assert checked == len(rooms)
