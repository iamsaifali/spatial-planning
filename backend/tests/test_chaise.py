"""Phase 3a — standalone chaise-lounge (living-room "Assist with AI").

The chaise-lounge is a STANDALONE lounge piece, opt-in via the checklist (`chaise_lounge`),
placed in a free corner facing the room. It must:
  * NEVER compete as a primary/secondary sofa (its own "chaise" placement role — the remap),
  * be OFF by default (the essentials-only default is byte-identical),
  * route every placement through the validation gate (always safe),
  * skip cleanly with a "didn't fit" notice when no clean spot survives.

These tests use a deterministic test-local catalog: the fixture catalog plus a SINGLE
chaise-lounge product, so the selector's choice is fixed.
"""

import json

import pytest

from spatial_planning.config import get_settings
from spatial_planning.models.geometry import Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import placement_group
from spatial_planning.services.catalog import CatalogRepository, set_repository
from spatial_planning.services.recommend.orchestrator import plan_layout_from_recipe

# Codes the validation gate must NEVER let through (safety spot-check).
UNSAFE_CODES = {"OVERLAP_ITEM", "OUT_OF_BOUNDS", "BLOCKS_DOOR_SWING", "BLOCKS_WALKWAY"}

# A large living room with a genuinely empty corner (matches CLAUDE.md's repro room).
BIG_LIVING = {
    "vertices": [[0, 0], [600, 0], [600, 520], [0, 520]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 85}],
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
GOLDEN_DEFAULT_PID = "lay_7ab3d93548"  # essentials-only default (unchanged by the opt-in chaise)

_CHAISE_PRODUCT = {
    "id": "chaise-test-001",
    "name": "Test Chaise Lounge",
    "brand": "Test Brand",
    "category": "chaise-lounge",
    "price": 720,
    "width_cm": 145,
    "depth_cm": 78,
    "height_cm": 82,
    "style_tags": ["modern"],
    "colors": ["Grey"],
    "materials": ["Linen"],
    "in_stock": True,
    "delivery_days": 4,
    "rating": 4.2,
    "attrs": {"seat_height_cm": 42},
    "image_url": "",
    "is_walkable": False,
    "shape": "rect",
    "description": "A standalone lounge chaise.",
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
