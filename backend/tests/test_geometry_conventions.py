"""Pins for the rotation/normal conventions every other module relies on."""

import math

from app.services.spatial.geometry_utils import (
    front_vector,
    item_polygon,
    rotation_for_normal,
    width_axis,
)


def approx(a: tuple[float, float], b: tuple[float, float], eps: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def test_front_vector_pins():
    assert approx(front_vector(0), (0.0, 1.0))  # faces down (into a top-wall room)
    assert approx(front_vector(90), (-1.0, 0.0))  # screen-clockwise
    assert approx(front_vector(180), (0.0, -1.0))
    assert approx(front_vector(270), (1.0, 0.0))


def test_width_axis_pins():
    assert approx(width_axis(0), (1.0, 0.0))
    assert approx(width_axis(90), (0.0, 1.0))


def test_rotation_for_normal_roundtrip():
    for nx, ny, expected in [(0, 1, 0.0), (0, -1, 180.0), (1, 0, 270.0), (-1, 0, 90.0)]:
        rot = rotation_for_normal((nx, ny))
        assert math.isclose(rot, expected, abs_tol=1e-9)
        assert approx(front_vector(rot), (nx, ny))


def test_rotated_item_bbox():
    poly = item_polygon(0, 0, 200, 90, 90)
    minx, miny, maxx, maxy = poly.bounds
    assert math.isclose(maxx - minx, 90, abs_tol=1e-6)
    assert math.isclose(maxy - miny, 200, abs_tol=1e-6)
