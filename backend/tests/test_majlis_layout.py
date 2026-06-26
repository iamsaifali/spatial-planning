"""P1: the Majlis perimeter-fill seating engine (pure geometry, no catalog/LLM)."""

from app.models.geometry import Room
from app.services.majlis.layout import fill_perimeter, total_seats
from app.services.majlis.validate import error_findings, validate_majlis
from app.services.spatial.analyze import analyze_room
from app.services.spatial.geometry_utils import dot, front_vector


def _room(w, d, doors=None, windows=None):
    return Room(
        vertices=[[0, 0], [w, 0], [w, d], [0, d]],
        doors=doors or [],
        windows=windows or [],
        wall_height_cm=270,
    )


def _analyze(w, d, **kw):
    return analyze_room(_room(w, d, **kw))


def test_fills_every_wall_with_no_errors():
    analysis = _analyze(600, 500)
    placed = fill_perimeter(analysis)
    walls_used = {p.wall_index for p in placed}
    assert walls_used == {0, 1, 2, 3}, "every wall should be seated"
    assert error_findings(validate_majlis(analysis, placed)) == []


def test_sofas_face_inward():
    analysis = _analyze(700, 600)
    for p in fill_perimeter(analysis):
        normal = analysis.walls[p.wall_index].normal
        # the sofa front (from its rotation) must point along the wall's inward normal
        assert dot(front_vector(p.rotation_deg), normal) > 0.99, "sofa must face the room centre"


def test_door_swing_stays_clear():
    doors = [{"id": "d1", "wall_index": 1, "offset_cm": 150, "width_cm": 90, "swing": "inward", "hinge": "left"}]
    analysis = _analyze(800, 600, doors=doors)
    placed = fill_perimeter(analysis)
    findings = validate_majlis(analysis, placed)
    assert all(f.code != "BLOCKS_DOOR_SWING" for f in findings)
    assert error_findings(findings) == []


def test_center_stays_open():
    analysis = _analyze(700, 700)
    findings = validate_majlis(analysis, fill_perimeter(analysis))
    assert all(f.code != "MAJLIS_CENTER_BLOCKED" for f in findings)


def test_deterministic():
    analysis = _analyze(880, 720)
    a = fill_perimeter(analysis)
    b = fill_perimeter(analysis)
    assert [(p.wall_index, p.x, p.y, p.rotation_deg, p.width_cm) for p in a] == \
           [(p.wall_index, p.x, p.y, p.rotation_deg, p.width_cm) for p in b]


def test_seats_scale_with_room():
    small = total_seats(fill_perimeter(_analyze(500, 450)))
    big = total_seats(fill_perimeter(_analyze(970, 930)))
    assert small > 0
    assert big > small, "a bigger room seats more around its longer walls"


def test_too_small_room_places_nothing_cleanly():
    analysis = _analyze(300, 260)  # walls too short after corner reserves
    placed = fill_perimeter(analysis)
    assert error_findings(validate_majlis(analysis, placed)) == []
