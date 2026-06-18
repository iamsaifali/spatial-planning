"""Deterministic seating-capacity maths feeding the layout plan."""

SEAT_CM_PER_PERSON = 60.0
SOFA_SEATS = 3  # a typical 3-seat sofa covers this many before extra seating is needed

# Sensible default headcount per purpose when the user doesn't specify one.
_DEFAULT_BY_PURPOSE = {
    "family": 4,
    "entertaining": 6,
    "compact_living": 2,
    "work_lounge": 3,
}


def target_capacity(prefs) -> int:
    if prefs.seating_capacity:
        return prefs.seating_capacity
    return _DEFAULT_BY_PURPOSE.get(prefs.room_purpose or "", 3)


def seating_target_cm(prefs) -> float:
    return target_capacity(prefs) * SEAT_CM_PER_PERSON


def extra_seats_as_chairs(prefs) -> int:
    """Accent chairs to add beyond the sofa to reach the seating target (0..4).
    The per-room cap (archetypes.caps_for) further bounds this by room size."""
    extra = max(0, target_capacity(prefs) - SOFA_SEATS)
    return min(4, extra)
