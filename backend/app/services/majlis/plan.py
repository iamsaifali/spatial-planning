"""Majlis layout plan.

P0 SCAFFOLD: returns an empty 'coming soon' plan so the room-type dispatch is wired and
isolated from the family engine without yet implementing perimeter seating. The real
plan (perimeter sofa fill + accessories) replaces this in later phases. This function is
deliberately self-contained: it does NOT touch the family director, its _plan_cache, or
the shared RoomAnalysis.
"""

from app.models.geometry import Room
from app.models.plan import LayoutPlan
from app.models.preferences import Preferences

_COMING_SOON = (
    "Majlis layouts are coming soon - seating will line every wall around an open centre."
)


def get_majlis_plan(room: Room, prefs: Preferences, placed=None) -> tuple[LayoutPlan, str]:
    """Returns (plan, source). P0 stub: an empty plan carrying a 'coming soon' note."""
    plan = LayoutPlan(archetype="majlis", items=[], rationale=_COMING_SOON, seating_note=_COMING_SOON)
    return plan, "template"
