"""Deterministic knowledge tables that condition (and bound) the layout plan.

These constrain what the LLM Director may produce and drive the heuristic fallback
when the LLM is unavailable. Geometry itself stays in services/spatial/zones.py - the
anchor here is the *intent* the LLM commits to and the resolver/zone engine honours.
"""

# Dependency-safe ordering: a category must come AFTER anything its placement
# anchors to (chairs/tv/rug anchor to the sofa, so sofa is first). Also the order
# the guided flow walks the user through.
CATEGORY_ORDER = [
    "sofa", "tv_unit", "rug", "coffee_table",
    "side_table", "accent_chair", "lighting", "storage", "decor",
]

# Per-category instance caps (baseline / small rooms) - the LLM's quantity is clamped to these.
QUANTITY_CAPS: dict[str, int] = {
    "sofa": 1, "tv_unit": 1, "rug": 1, "coffee_table": 1,
    "side_table": 2, "accent_chair": 2, "lighting": 3, "storage": 2, "decor": 4,
}


def caps_for(area_m2: float) -> dict[str, int]:
    """Quantity caps scaled to room area so a large room can hold more soft
    seating, lighting and decor (a big space shouldn't get a small room's count).
    Sofa/TV/rug/coffee stay single - one main seating group (size handled by scoring)."""
    caps = dict(QUANTITY_CAPS)
    if area_m2 >= 35.0:
        caps.update({"accent_chair": 4, "side_table": 3, "lighting": 5, "storage": 3, "decor": 6})
    if area_m2 >= 60.0:
        caps.update({"accent_chair": 6, "lighting": 6, "decor": 8})
    return caps

# Default (anchor, anchor_ref) per category - the natural arrangement intent.
DEFAULT_ANCHORS: dict[str, tuple[str, str]] = {
    "sofa": ("on_focal_wall", "focal_wall"),
    "tv_unit": ("facing", "sofa"),
    "rug": ("in_front_of", "sofa"),
    "coffee_table": ("in_front_of", "sofa"),
    "side_table": ("flanking", "sofa"),
    "accent_chair": ("conversation_angle", "sofa"),
    "lighting": ("corner", "room"),
    "storage": ("on_focal_wall", "room"),
    "decor": ("corner", "room"),
}

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
