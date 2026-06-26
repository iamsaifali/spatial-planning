"""Deterministic knowledge tables that condition (and bound) the layout plan.

These constrain what the LLM Director may produce. Placement itself is owned by the
per-category geometric rules in services/spatial - this module only governs the plan's
*content* (which categories, how many, in what order).
"""

# Dependency-safe ordering: a category must come AFTER anything its placement
# depends on (chairs/tv/rug are positioned relative to the sofa, so sofa is first).
# Also the order the guided flow walks the user through.
CATEGORY_ORDER = [
    "sofa", "tv_unit", "rug", "coffee_table",
    "side_table", "accent_chair", "lighting", "storage", "decor",
]

# Per-category instance caps (baseline / small rooms) - the LLM's quantity is clamped to
# these. Tuned to a MODERN FAMILY living room: one media console, a floor lamp or two, a
# couple of plants - NOT a showroom. A big room scales seating (sofas/chairs/side tables),
# but soft clutter (lighting/storage/decor) only nudges up. The geometry engine then skips
# any planned unit that has no clean spot, so these are ceilings, not targets.
QUANTITY_CAPS: dict[str, int] = {
    "sofa": 1, "tv_unit": 1, "rug": 1, "coffee_table": 1,
    "side_table": 2, "accent_chair": 2, "lighting": 1, "storage": 1, "decor": 2,
}


def caps_for(area_m2: float) -> dict[str, int]:
    """Quantity caps scaled to room area. TV/rug/coffee stay single (one media wall / one
    seating zone). The SOFA cap scales so larger rooms can form an L (2) or U (3); the
    geometry engine is the final arbiter of whether the extra sofa actually fits."""
    caps = dict(QUANTITY_CAPS)
    if area_m2 >= 22.0:
        caps.update({"sofa": 2, "lighting": 2})  # room for an L-shape + a 2nd floor lamp
    if area_m2 >= 40.0:
        # U-shape seating; a sideboard alongside the media console; a 3rd plant. Side
        # tables stay at 2 - one per sofa end is plenty; a 3rd just crowds the seating.
        caps.update({"sofa": 3, "accent_chair": 3, "storage": 2, "decor": 3})
    if area_m2 >= 60.0:
        caps["accent_chair"] = 4  # a big room can seat a 4th accent chair
    return caps

# Which categories suit each living-room purpose, in priority order.
PURPOSE_RULES: dict[str, list[str]] = {
    "family": ["sofa", "tv_unit", "rug", "coffee_table", "storage", "lighting", "side_table", "accent_chair", "decor"],
    "entertaining": ["sofa", "accent_chair", "coffee_table", "rug", "side_table", "lighting", "tv_unit", "decor"],
    "compact_living": ["sofa", "coffee_table", "rug", "storage", "lighting", "tv_unit"],
    "work_lounge": ["sofa", "accent_chair", "storage", "lighting", "coffee_table", "rug", "tv_unit"],
}

# Categories a style tends to drop (keeps minimal/industrial rooms uncluttered).
STYLE_DROP: dict[str, set[str]] = {
    "minimal": {"decor", "side_table"},
    "industrial": {"decor"},
    "scandinavian": set(),
    "boho": set(),
    "classic": set(),
    "modern": set(),
}


def order_index(category: str) -> int:
    return CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else 99


def candidate_categories(prefs) -> list[str]:
    """Purpose-driven category shortlist, minus style drops, sofa guaranteed."""
    base = PURPOSE_RULES.get(prefs.room_purpose or "", CATEGORY_ORDER)
    drop: set[str] = set()
    for style in prefs.styles:
        drop |= STYLE_DROP.get(style, set())
    cats = [c for c in base if c not in drop]
    if "sofa" not in cats:
        cats.insert(0, "sofa")
    return cats


def archetype_name(prefs) -> str:
    purpose = prefs.room_purpose or "balanced"
    style = prefs.styles[0] if prefs.styles else "warm"
    return f"{style}_{purpose}"
