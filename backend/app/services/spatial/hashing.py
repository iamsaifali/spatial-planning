"""Canonical room hashing for the analysis cache."""

import hashlib
import json

from app.models.geometry import Room


def room_hash(room: Room) -> str:
    payload = {
        "v": [(round(x, 1), round(y, 1)) for x, y in room.vertices],
        "d": sorted(
            (
                d.wall_index,
                round(d.offset_cm, 1),
                round(d.width_cm, 1),
                d.swing,
                d.hinge,
            )
            for d in room.doors
        ),
        "w": sorted(
            (
                w.wall_index,
                round(w.offset_cm, 1),
                round(w.width_cm, 1),
                round(w.sill_height_cm, 1),
                round(w.height_cm, 1),
            )
            for w in room.windows
        ),
        "h": round(room.wall_height_cm, 1),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
