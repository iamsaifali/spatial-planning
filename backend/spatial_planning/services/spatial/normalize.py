"""Room semantic validation (shape checks beyond pydantic field ranges)."""

import math

from shapely.geometry import Polygon
from shapely.validation import explain_validity

from spatial_planning.errors import (
    OPENING_INVALID,
    ROOM_INVALID,
    ROOM_TOO_LARGE,
    ROOM_TOO_SMALL,
    AppError,
)
from spatial_planning.models.analysis import RoomIssue
from spatial_planning.models.geometry import MAX_BBOX_CM, MIN_AREA_CM2, Room


def _wall_length(room: Room, i: int) -> float:
    n = len(room.vertices)
    ax, ay = room.vertices[i]
    bx, by = room.vertices[(i + 1) % n]
    return math.hypot(bx - ax, by - ay)


def collect_room_issues(room: Room) -> list[RoomIssue]:
    """All semantic problems with a drawn room; empty list means valid."""
    issues: list[RoomIssue] = []
    n = len(room.vertices)

    for i in range(n):
        if _wall_length(room, i) < 1.0:
            issues.append(
                RoomIssue(
                    code=ROOM_INVALID,
                    message=f"Wall {i} is shorter than 1 cm (duplicate corner).",
                    wall_index=i,
                )
            )

    poly = Polygon(room.vertices)
    if not poly.is_valid:
        issues.append(
            RoomIssue(
                code=ROOM_INVALID,
                message=f"Room outline is invalid: {explain_validity(poly)}.",
            )
        )
        return issues  # downstream checks meaningless

    if poly.area < MIN_AREA_CM2:
        issues.append(
            RoomIssue(
                code=ROOM_TOO_SMALL,
                message=f"Room is {poly.area / 10_000:.1f} m2 - minimum supported size is 2 m2.",
            )
        )
    minx, miny, maxx, maxy = poly.bounds
    if (maxx - minx) > MAX_BBOX_CM or (maxy - miny) > MAX_BBOX_CM:
        issues.append(
            RoomIssue(
                code=ROOM_TOO_LARGE,
                message="Room exceeds the 30 m maximum side length.",
            )
        )

    for kind, openings in (("door", room.doors), ("window", room.windows)):
        for op in openings:
            if op.wall_index >= n:
                issues.append(
                    RoomIssue(
                        code=OPENING_INVALID,
                        message=f"{kind} '{op.id}' references wall {op.wall_index}, "
                        f"but the room has {n} walls.",
                        wall_index=op.wall_index,
                    )
                )
                continue
            wall_len = _wall_length(room, op.wall_index)
            if op.offset_cm + op.width_cm > wall_len + 0.5:
                issues.append(
                    RoomIssue(
                        code=OPENING_INVALID,
                        message=f"{kind} '{op.id}' ({op.width_cm:.0f} cm at offset "
                        f"{op.offset_cm:.0f} cm) does not fit wall {op.wall_index} "
                        f"({wall_len:.0f} cm long).",
                        wall_index=op.wall_index,
                    )
                )

    # vertical sanity: openings must fit under the ceiling
    for door in room.doors:
        if door.height_cm > room.wall_height_cm - 5:
            issues.append(
                RoomIssue(
                    code=OPENING_INVALID,
                    message=f"door '{door.id}' ({door.height_cm:.0f} cm tall) does not fit "
                    f"under the {room.wall_height_cm:.0f} cm ceiling.",
                    wall_index=door.wall_index,
                )
            )
    for win in room.windows:
        if win.sill_height_cm + win.height_cm > room.wall_height_cm - 5:
            issues.append(
                RoomIssue(
                    code=OPENING_INVALID,
                    message=f"window '{win.id}' (sill {win.sill_height_cm:.0f} + "
                    f"{win.height_cm:.0f} cm) does not fit under the "
                    f"{room.wall_height_cm:.0f} cm ceiling.",
                    wall_index=win.wall_index,
                )
            )
    return issues


def require_valid_room(room: Room) -> Polygon:
    """Raise AppError on the first blocking issue; return the shapely polygon."""
    issues = collect_room_issues(room)
    if issues:
        first = issues[0]
        raise AppError(
            code=first.code,
            message=first.message,
            status_code=422,
            details=[i.model_dump() for i in issues],
        )
    return Polygon(room.vertices)
