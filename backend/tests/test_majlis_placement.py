"""Phase 4: real Saudi Majlis perimeter placement.

room_type="majlis" should line seating along the walls, keep the centre open with a
centred rug + low table, respect doors/windows, prioritise seating capacity, and
never produce a TV-first layout - all without changing living-room behaviour.
"""

import math

from app.models.geometry import PlacedItem, Room
from app.models.preferences import Preferences
from app.models.validation import MUST_FIX_CODES
from app.services.catalog import get_repository
from app.services.guide.flow import MAJLIS_SEQUENCE, sequence_for_room_type
from app.services.recommend.orchestrator import plan_layout
from app.services.spatial.analyze import analyze_room
from app.services.spatial.validate import validate_item

# A generous salon so benches can line several walls; door on the top wall.
SALON = {
    "vertices": [[0, 0], [600, 0], [600, 560], [0, 560]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 250, "width_cm": 100}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 200, "width_cm": 180}],
    "wall_height_cm": 300,
}
CENTER = (300.0, 280.0)


def _room(spec=SALON) -> Room:
    return Room.model_validate(spec)


def _plan(seating_capacity=10, **pref_over):
    prefs = Preferences(room_type="majlis", seating_capacity=seating_capacity, **pref_over)
    return plan_layout(room=_room(), preferences=prefs, placed_items=[])


def _is_perimeter(p) -> bool:
    return "majlis_perimeter_seating" in p.reason_codes


# --- sequence ---------------------------------------------------------------------


def test_majlis_uses_majlis_sequence():
    seq = sequence_for_room_type("majlis")
    assert seq == MAJLIS_SEQUENCE
    assert seq[0] == "sofa"  # seating first
    assert "tv_unit" not in seq  # NOT a TV-first room


# --- perimeter seating ------------------------------------------------------------


def test_majlis_seating_is_perimeter(catalog_repo):
    resp = _plan(seating_capacity=10)
    benches = [p for p in resp.placements if p.category == "sofa"]
    assert len(benches) >= 2  # seating lined along multiple walls
    assert all(_is_perimeter(b) for b in benches)
    # benches sit on distinct wall bands (no duplicate on the same segment)
    assert len({b.zone_id for b in benches}) == len(benches)
    # every bench is a Majlis product
    for b in benches:
        assert "majlis" in b.product.room_types


def test_majlis_more_seats_when_target_high(catalog_repo):
    low = _plan(seating_capacity=4)
    high = _plan(seating_capacity=12)
    low_seats = sum(p.product.seating_capacity for p in low.placements if p.category == "sofa")
    high_seats = sum(p.product.seating_capacity for p in high.placements if p.category == "sofa")
    assert high_seats >= low_seats
    assert high_seats >= 8  # a high target lines several benches


def test_majlis_seating_capacity_reached(catalog_repo):
    resp = _plan(seating_capacity=10)
    total_seats = sum(p.product.seating_capacity for p in resp.placements)
    assert total_seats >= 10  # target met (benches + optional cushions)


def test_majlis_default_seat_target_scales_with_area(catalog_repo):
    # no seating_capacity preference -> area-based target still lines benches
    prefs = Preferences(room_type="majlis")
    resp = plan_layout(room=_room(), preferences=prefs, placed_items=[])
    benches = [p for p in resp.placements if p.category == "sofa"]
    assert len(benches) >= 2


# --- centre kept open -------------------------------------------------------------


def test_majlis_center_has_rug_and_table_only(catalog_repo):
    resp = _plan(seating_capacity=10)

    def near_center(p, tol):
        return math.hypot(p.pose.x - CENTER[0], p.pose.y - CENTER[1]) <= tol

    rug = [p for p in resp.placements if p.category == "rug"]
    table = [p for p in resp.placements if p.category == "coffee_table"]
    assert rug and near_center(rug[0], 120)  # rug centred
    assert table and near_center(table[0], 120)  # low table centred (on the rug)
    # seating is NOT in the centre - it hugs the walls
    for b in (p for p in resp.placements if p.category == "sofa"):
        assert not near_center(b, 150)


# --- validity: doors, windows, collisions -----------------------------------------


def test_majlis_layout_has_no_hard_errors(catalog_repo):
    resp = _plan(seating_capacity=10)
    analysis = analyze_room(_room())
    repo = get_repository()
    placed: list = []
    for p in resp.placements:
        item = PlacedItem(
            instance_id=p.instance_id, product_id=p.product_id,
            x=p.pose.x, y=p.pose.y, rotation_deg=p.pose.rotation_deg,
        )
        product = repo.require(p.product_id)
        findings = validate_item(analysis, placed, item, product)
        assert not [f for f in findings if f.code in MUST_FIX_CODES], (p.category, findings)
        placed.append((item, product))


def test_majlis_door_not_blocked(catalog_repo):
    resp = _plan(seating_capacity=12)
    codes = {f.code for f in resp.findings}
    assert "BLOCKS_DOOR_SWING" not in codes
    assert "BLOCKS_WALKWAY" not in codes
    assert not [f for f in resp.findings if f.severity == "error"]


# --- isolation: living-room flow unchanged ----------------------------------------


def test_living_room_flow_unchanged(catalog_repo):
    lr = plan_layout(room=_room(), preferences=Preferences(styles=["modern"]), placed_items=[])
    # no Majlis leakage, no perimeter seating, sequence still includes tv_unit pick
    assert all("majlis" not in p.product.room_types for p in lr.placements)
    assert not any(_is_perimeter(p) for p in lr.placements)
    sofas = [p for p in lr.placements if p.category == "sofa"]
    assert len(sofas) == 1  # living room = a single sofa, not perimeter benches


# --- fallback when Majlis products are unavailable --------------------------------


def test_majlis_fallback_when_no_majlis_products(catalog_repo):
    from app.services.catalog import CatalogRepository, set_repository

    original = get_repository()
    living_only = CatalogRepository([p for p in original.all() if "majlis" not in p.room_types])
    set_repository(living_only)
    try:
        resp = plan_layout(
            room=_room(), preferences=Preferences(room_type="majlis", seating_capacity=8), placed_items=[]
        )
        # selector falls back to living-room sofas; must not crash or return invalid
        assert resp.proposal_id.startswith("lay_")
        assert not [f for f in resp.findings if f.severity == "error"]
    finally:
        set_repository(original)
