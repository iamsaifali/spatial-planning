"""Phase 3b — dining set (table + chair ring in a separate zone), living-room "Assist with AI".

The dining set is an OPT-IN group gated by the single checklist piece ``dining_set``: a dining
TABLE placed in its OWN open pocket BESIDE the conversation group (never overlapping the sofa /
L-return / rug / coffee table), with dining CHAIRS ringed around it. It must:
  * be OFF by default (the essentials-only default layout is byte-identical),
  * gate the WHOLE group — opting out drops BOTH the table and the chairs,
  * never orphan chairs — if the table can't fit, no chairs (plus a "didn't fit" notice),
  * route every piece through the validation gate (always safe),
  * sit in a genuinely separate pocket (no overlap with the seating group).

These tests use a deterministic test-local catalog: the fixture catalog plus one dining table and
one dining chair (both living-room), so the selector's choices are fixed.
"""

import json

import pytest
from shapely.geometry import Polygon

from spatial_planning.config import get_settings
from spatial_planning.models.geometry import Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.services.catalog import CatalogRepository, set_repository
from spatial_planning.services.recommend.orchestrator import plan_layout_from_recipe
from spatial_planning.services.spatial.geometry_utils import item_polygon

# Codes the validation gate must NEVER let through (safety spot-check).
UNSAFE_CODES = {"OVERLAP_ITEM", "OUT_OF_BOUNDS", "BLOCKS_DOOR_SWING", "BLOCKS_WALKWAY"}

# A large living room with plenty of open floor for a separate dining area.
BIG_LIVING = {
    "vertices": [[0, 0], [700, 0], [700, 600], [0, 600]],
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
TINY = {  # too cramped for a separate dining pocket beside the seating
    "vertices": [[0, 0], [300, 0], [300, 280], [0, 280]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 20, "width_cm": 80}],
    "windows": [],
}
GOLDEN_DEFAULT_PID = "lay_ba2a72c11d"  # essentials-only default (unchanged by the opt-in dining set)

_TABLE = {
    "id": "dining-table-001", "name": "Test Dining Table",
    "category": "dining-table", "price": 620, "width_cm": 150, "depth_cm": 90, "height_cm": 75,
    "style_tags": ["modern"], "colors": ["Oak"], "image_url": "", "is_walkable": False,
    "shape": "rect", "room_types": ["living_room"],
    "seating_capacity": 0,
}
_CHAIR = {
    "id": "dining-chair-001", "name": "Test Dining Chair",
    "category": "chair", "price": 90, "width_cm": 48, "depth_cm": 52, "height_cm": 92,
    "style_tags": ["modern"], "colors": ["Oak"], "image_url": "", "is_walkable": False,
    "shape": "rect", "room_types": ["living_room"],
    "seating_capacity": 1,
}

ESSENTIALS = ["rug", "coffee_table", "tv_unit", "floor_lamp"]


def _room(spec):
    return Room.model_validate(spec)


def _prefs(pieces=None):
    return Preferences(styles=["modern"], included_pieces=pieces)


@pytest.fixture()
def dining_repo(tmp_path):
    """The fixture catalog PLUS one dining table + one dining chair — deterministic, and the
    only dining products the selector can choose. Installed as the active repository."""
    settings = get_settings()
    base = json.loads((settings.resolve("spatial_planning/data/catalog.json")).read_text())
    catalog = base + [dict(_TABLE), dict(_CHAIR)]
    path = tmp_path / "catalog_with_dining.json"
    path.write_text(json.dumps(catalog))
    repo = CatalogRepository.load(path, settings.resolve(settings.static_dir))
    set_repository(repo)
    return repo


def _cats(resp):
    return {p.category for p in resp.placements}


def _poly(p):
    return item_polygon(p.pose.x, p.pose.y, p.product.width_cm, p.product.depth_cm, p.pose.rotation_deg)


def _table(resp):
    tables = [p for p in resp.placements if p.category == "dining_table"]
    return tables[0] if tables else None


def _dining_chairs(resp, table):
    """Chairs ringed around the dining table (within a chair-ring radius of its centre)."""
    if table is None:
        return []
    radius = max(table.product.width_cm, table.product.depth_cm)  # comfortably covers the ring
    return [
        p for p in resp.placements
        if p.category == "accent_chair"
        and abs(p.pose.x - table.pose.x) <= radius and abs(p.pose.y - table.pose.y) <= radius
    ]


# --- 1. dining set places when opted in: a separate table + a chair ring, all valid -----


def test_dining_places_when_opted_in(dining_repo):
    resp = plan_layout_from_recipe(_room(BIG_LIVING), _prefs(ESSENTIALS + ["dining_set"]), [])
    table = _table(resp)
    assert table is not None, resp.notices
    assert table.product.category == "dining-table"
    assert table.product.id == "dining-table-001"

    chairs = _dining_chairs(resp, table)
    assert len(chairs) >= 1  # at least one chair ringed around the table
    for c in chairs:
        assert c.product.category == "chair"  # dining chairs use the "chair" store category

    # every placement valid — no unsafe finding anywhere in the layout
    assert not [f for f in resp.findings if f.code in UNSAFE_CODES]
    assert not [f for f in resp.findings if f.severity == "error"]


# --- 2. off by default; essentials-only default PID unchanged ----------------------------


def test_default_has_no_dining_and_pid_unchanged(catalog_repo):
    # essentials-only default (included_pieces=None) never runs the dining roles.
    resp = plan_layout_from_recipe(_room(LIVING_ROOM), _prefs(None), [])
    assert "dining_table" not in _cats(resp)
    assert resp.proposal_id == GOLDEN_DEFAULT_PID  # byte-identical to the pre-dining default


def test_default_has_no_dining_even_with_dining_in_catalog(dining_repo):
    # Dining products are available, but the default doesn't opt them in -> nothing, no notice.
    resp = plan_layout_from_recipe(_room(BIG_LIVING), _prefs(None), [])
    assert "dining_table" not in _cats(resp)
    assert not any("dining" in n.lower() for n in resp.notices)


# --- 3. opt-out gates the WHOLE group (neither table nor chairs) --------------------------


def test_opt_out_has_no_dining_pieces(dining_repo):
    # A list WITHOUT dining_set -> the dining roles never run: no table, and no orphan chairs
    # around a (non-existent) table. (Companion accent chairs near the sofa are unrelated.)
    resp = plan_layout_from_recipe(_room(BIG_LIVING), _prefs(ESSENTIALS + ["side_table", "console"]), [])
    assert "dining_table" not in _cats(resp)
    assert _dining_chairs(resp, _table(resp)) == []


# --- 4. table can't fit -> NO table AND NO orphan chairs + a "didn't fit" notice ---------


def test_tiny_room_no_table_no_orphan_chairs(dining_repo):
    resp = plan_layout_from_recipe(_room(TINY), _prefs(["dining_set"]), [])
    assert "dining_table" not in _cats(resp)  # no separate pocket -> skipped
    assert _dining_chairs(resp, None) == []  # the chairs role found no table -> no orphans
    # the whole layout (whatever fit) is still safe
    assert not [f for f in resp.findings if f.code in UNSAFE_CODES]
    # honest notice that the requested set didn't fit
    assert "The dining set didn't fit this room." in resp.notices


# --- 5. the dining group sits in a SEPARATE pocket (no overlap with the seating group) ----


def test_dining_never_overlaps_seating_group(dining_repo):
    resp = plan_layout_from_recipe(_room(BIG_LIVING), _prefs(ESSENTIALS + ["dining_set"]), [])
    table = _table(resp)
    assert table is not None, resp.notices

    seating = [p for p in resp.placements if p.category in ("sofa", "rug", "coffee_table")]
    assert seating  # the conversation group is present
    dining_polys = [_poly(table)] + [_poly(c) for c in _dining_chairs(resp, table)]
    for d in dining_polys:
        for s in seating:
            inter = d.intersection(_poly(s))
            # a genuinely separate pocket: no meaningful overlap with any seating-group piece
            assert inter.area < 1.0, (table.pose, s.category)


# --- 6. safety sweep: every opted-in dining layout is gate-clean --------------------------


def test_dining_safety_sweep(dining_repo):
    rooms = [
        BIG_LIVING,
        LIVING_ROOM,
        TINY,
        {  # door on a side wall + a window
            "vertices": [[0, 0], [640, 0], [640, 520], [0, 520]],
            "doors": [{"id": "d1", "wall_index": 1, "offset_cm": 60, "width_cm": 90}],
            "windows": [{"id": "w1", "wall_index": 0, "offset_cm": 200, "width_cm": 160}],
        },
        {  # two doors
            "vertices": [[0, 0], [660, 0], [660, 560], [0, 560]],
            "doors": [
                {"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90},
                {"id": "d2", "wall_index": 3, "offset_cm": 60, "width_cm": 85},
            ],
            "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 240, "width_cm": 200}],
        },
    ]
    incl = ESSENTIALS + ["chaise_lounge", "dining_set", "side_table", "console", "plant", "vases"]
    checked = 0
    for spec in rooms:
        resp = plan_layout_from_recipe(_room(spec), _prefs(incl), [])
        bad = [f for f in resp.findings if f.code in UNSAFE_CODES]
        assert not bad, (spec["vertices"][2], bad)
        checked += 1
    assert checked == len(rooms)
