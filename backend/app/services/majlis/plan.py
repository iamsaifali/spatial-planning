"""Majlis layout plan (guided flow).

Returns a plan whose steps drive the SAME guided UX as the family room - Sofa (one per
perimeter slot), Rug, Side table, Lighting, Decor - so the user gets product
recommendations and places one at a time. Placement positions come from majlis/zones.py.
Self-contained: does not touch the family director or its caches.
"""

from app.models.geometry import Room
from app.models.plan import LayoutPlan, PlanItem
from app.models.preferences import Preferences
from app.services.catalog import get_repository
from app.services.majlis.zones import SEATS_PER_SOFA, count_sofa_slots
from app.services.spatial.analyze import analyze_room

# the majlis step sequence (no TV): perimeter sofas, central rug + low central coffee
# table (Gulf majlis serving tray), then side tables + lamp + plant spread across corners.
# `fill=True` marks an OPEN-ENDED step: the user keeps placing until the walls are full,
# so the count is never capped by an up-front guess (sofa width varies widely).
_ITEMS = (
    ("sofa", "essential", 1, True),
    ("rug", "essential", 3, False),
    ("coffee_table", "essential", 4, False),
    ("side_table", "non_essential", 5, False),
    ("lighting", "non_essential", 7, False),
    ("decor", "non_essential", 9, False),
)


def get_majlis_plan(room: Room, prefs: Preferences, placed=None) -> tuple[LayoutPlan, str]:
    analysis = analyze_room(room)
    stats = get_repository().category_stats()
    s = stats.get("sofa", {})
    # Seat estimate is a RANGE, not a cap: narrow sofas seat more, wide sofas fewer. The actual
    # number the user places is decided live by the geometry (fill step), not this number.
    hi = max(1, count_sofa_slots(analysis, stats, width=s.get("min_w", 152.0)))
    lo = max(1, count_sofa_slots(analysis, stats, width=s.get("max_w", 260.0)))
    lo, hi = min(lo, hi), max(lo, hi)
    # quantity is now only a soft hint (the fill step ignores it as a cap); clamp it to the
    # PlanItem field ceiling so a big room's narrow-sofa estimate can't overflow validation.
    sofa_qty = max(1, min(hi, 12))
    quantities = {"sofa": sofa_qty, "rug": 1, "coffee_table": 1, "side_table": 2, "lighting": 1, "decor": 2}
    items = [
        PlanItem(category=cat, quantity=quantities[cat], tier=tier, priority=prio, fill=fill)
        for cat, tier, prio, fill in _ITEMS
    ]
    seats_lo, seats_hi = lo * SEATS_PER_SOFA, hi * SEATS_PER_SOFA
    if not seats_hi:
        note = "This room is too small for a majlis - try a larger room."
    elif seats_lo == seats_hi:
        note = f"Seats roughly {seats_hi} - keep adding sofas until the walls fill."
    else:
        note = (
            f"Seats roughly {seats_lo}-{seats_hi} depending on the sofas you pick - "
            "keep adding until the walls fill."
        )
    plan = LayoutPlan(archetype="majlis", items=items, rationale=note, seating_note=note)
    return plan, "template"
