import math

from shapely.prepared import prep

from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.normalize import require_valid_room
from spatial_planning.services.spatial.walls import build_walls


def test_wall_lengths_and_normals(rect_room):
    poly = require_valid_room(rect_room)
    walls, _ = build_walls(rect_room, poly, prep(poly))
    assert [round(w.length) for w in walls] == [480, 360, 480, 360]
    # inward normals point into the rectangle
    assert walls[0].normal == (0.0, 1.0)  # top wall
    assert walls[1].normal == (-1.0, 0.0)  # right wall
    assert walls[2].normal == (0.0, -1.0)  # bottom wall
    assert walls[3].normal == (1.0, 0.0)  # left wall


def test_clear_segments_subtract_openings(rect_room):
    analysis = analyze_room(rect_room)
    wall0 = analysis.walls[0]
    # door 40..130 with 10 cm jambs -> blocked 30..140
    assert [(round(a), round(b)) for a, b in wall0.clear_floor] == [(0, 30), (140, 480)]
    wall2 = analysis.walls[2]
    # window doesn't block floor furniture...
    assert [(round(a), round(b)) for a, b in wall2.clear_floor] == [(0, 480)]
    # ...but blocks solid-wall furniture
    assert [(round(a), round(b)) for a, b in wall2.clear_solid] == [(0, 140), (320, 480)]


def test_swing_arc_area_and_containment(rect_room):
    analysis = analyze_room(rect_room)
    arc = analysis.swing_arcs["d1"]
    expected = math.pi * 90 * 90 / 4
    assert abs(arc.area - expected) / expected < 0.05
    assert arc.within(analysis.polygon.buffer(0.5))


def test_window_strip_and_entry_clearance(rect_room):
    analysis = analyze_room(rect_room)
    assert "w1" in analysis.window_strips
    strip, sill = analysis.window_strips["w1"]
    assert sill == 90
    assert abs(strip.area - 180 * 40) / (180 * 40) < 0.05
    assert "d1" in analysis.entry_clearances


def test_corridor_connects_entry_to_interior(rect_room, l_room):
    for room in (rect_room, l_room):
        analysis = analyze_room(room)
        assert analysis.entries
        assert analysis.corridors, "expected at least one corridor"
        for corridor in analysis.corridors:
            assert corridor.polygon.area > 0
            assert corridor.polygon.within(analysis.polygon.buffer(1.0))


def test_l_room_two_entries_linked(l_room):
    analysis = analyze_room(l_room)
    pair = [c for c in analysis.corridors if c.from_label.startswith("door") and c.to_label.startswith("door")]
    assert pair, "expected an entry-to-entry corridor"
