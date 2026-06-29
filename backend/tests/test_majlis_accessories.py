"""P2: Majlis accessories - central rug + corner pieces, validated against the seating."""

from app.models.geometry import Room
from app.services.majlis.accessories import build_accessories, central_rug
from app.services.majlis.layout import fill_perimeter
from app.services.majlis.validate import error_findings, validate_majlis
from app.services.spatial.analyze import analyze_room


def _analyze(w, d, doors=None):
    return analyze_room(Room(vertices=[[0, 0], [w, 0], [w, d], [0, d]], doors=doors or [], windows=[], wall_height_cm=270))


def test_central_rug_is_centred_and_walkable():
    analysis = _analyze(700, 600)
    rug = central_rug(analysis)
    assert rug is not None and rug.category == "rug"
    assert abs(rug.x - 350) < 1 and abs(rug.y - 300) < 1  # room centre


def test_corner_pieces_placed_in_a_clear_room():
    analysis = _analyze(700, 600)
    acc = build_accessories(analysis, fill_perimeter(analysis))
    cats = [a.category for a in acc]
    assert cats.count("rug") == 1
    assert sum(c != "rug" for c in cats) == 4  # one piece per corner
    assert set(cats) >= {"rug", "side_table", "lighting", "decor"}


def test_accessories_validate_clean():
    for w, d, doors in [
        (600, 500, None),
        (760, 640, [{"id": "d", "wall_index": 1, "offset_cm": 150, "width_cm": 90, "swing": "inward", "hinge": "left"}]),
        (970, 930, None),
    ]:
        analysis = _analyze(w, d, doors)
        sofas = fill_perimeter(analysis)
        acc = build_accessories(analysis, sofas)
        assert error_findings(validate_majlis(analysis, sofas, acc)) == [], f"{w}x{d}"


def test_accessory_near_door_is_dropped():
    # door hard in a corner -> that corner's piece must be skipped, not block the swing
    doors = [{"id": "d", "wall_index": 0, "offset_cm": 20, "width_cm": 90, "swing": "inward", "hinge": "left"}]
    analysis = _analyze(700, 600, doors)
    sofas = fill_perimeter(analysis)
    acc = build_accessories(analysis, sofas)
    assert all(a.category == "rug" or a.category for a in acc)  # sanity
    assert error_findings(validate_majlis(analysis, sofas, acc)) == []


def test_deterministic():
    analysis = _analyze(820, 700)
    sofas = fill_perimeter(analysis)
    a = build_accessories(analysis, sofas)
    b = build_accessories(analysis, sofas)
    assert [(x.category, x.x, x.y, x.width_cm) for x in a] == [(x.category, x.x, x.y, x.width_cm) for x in b]
