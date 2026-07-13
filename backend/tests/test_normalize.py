import pytest

from spatial_planning.errors import OPENING_INVALID, ROOM_INVALID, ROOM_TOO_LARGE, ROOM_TOO_SMALL, AppError
from spatial_planning.models.geometry import Door, Room
from spatial_planning.services.spatial.normalize import collect_room_issues, require_valid_room


def test_valid_room_passes(rect_room):
    assert collect_room_issues(rect_room) == []
    poly = require_valid_room(rect_room)
    assert poly.area == 480 * 360


def test_bowtie_rejected(bowtie_room):
    issues = collect_room_issues(bowtie_room)
    assert any(i.code == ROOM_INVALID for i in issues)
    with pytest.raises(AppError) as err:
        require_valid_room(bowtie_room)
    assert err.value.code == ROOM_INVALID


def test_duplicate_corner_rejected():
    room = Room(vertices=[(0, 0), (0.5, 0.2), (400, 0), (400, 300), (0, 300)])
    issues = collect_room_issues(room)
    assert any(i.code == ROOM_INVALID for i in issues)


def test_too_small():
    room = Room(vertices=[(0, 0), (100, 0), (100, 100), (0, 100)])
    assert any(i.code == ROOM_TOO_SMALL for i in collect_room_issues(room))


def test_too_large():
    room = Room(vertices=[(0, 0), (3500, 0), (3500, 300), (0, 300)])
    assert any(i.code == ROOM_TOO_LARGE for i in collect_room_issues(room))


def test_door_wider_than_wall():
    room = Room(
        vertices=[(0, 0), (300, 0), (300, 300), (0, 300)],
        doors=[Door(id="d1", wall_index=0, offset_cm=200, width_cm=150)],
    )
    issues = collect_room_issues(room)
    assert any(i.code == OPENING_INVALID and i.wall_index == 0 for i in issues)


def test_opening_on_missing_wall():
    room = Room(
        vertices=[(0, 0), (300, 0), (300, 300), (0, 300)],
        doors=[Door(id="d1", wall_index=7, offset_cm=0, width_cm=90)],
    )
    assert any(i.code == OPENING_INVALID for i in collect_room_issues(room))


def test_clockwise_vertex_order_also_valid():
    room = Room(vertices=[(0, 0), (0, 300), (400, 300), (400, 0)])
    assert collect_room_issues(room) == []
