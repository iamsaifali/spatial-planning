"""Catalog migration / backfill for the room-type / seating-capacity fields.

Existing catalog rows (and any re-generated seed) may predate the room_types /
seating_capacity fields. Rather than rewrite the JSON seed, we backfill missing fields
at load time so every legacy product keeps working as a generic living-room item. The
only field that needs computation is seating_capacity, which is inferred from category +
width; a static model default can't do that.

This is intentionally pure and side-effect-free so it is easy to unit-test and so the
same defaults apply no matter where the catalog is loaded from.
"""

# Categories whose seating capacity is a fixed single seat regardless of width.
_SINGLE_SEAT_CATEGORIES = {"accent_chair", "floor_cushion", "ottoman_pouf"}
# Bench-like seating where capacity scales with width.
_BENCH_SEAT_CATEGORIES = {"sofa", "majlis_sofa", "majlis_seating"}
# Nominal width (cm) occupied by one seated person on a bench/sofa.
SEAT_WIDTH_CM = 75.0

# Defaults for the additive room-type fields (mirror app/models/products.py).
_DEFAULTS: dict[str, object] = {
    "room_types": ["living_room"],
}


def infer_seating_capacity(category: str, width_cm: float) -> int:
    """Seats a single SKU provides. 0 for non-seating categories."""
    if category in _SINGLE_SEAT_CATEGORIES:
        return 1
    if category in _BENCH_SEAT_CATEGORIES:
        return max(1, round((width_cm or 0.0) / SEAT_WIDTH_CM))
    return 0


def backfill_product(entry: dict) -> dict:
    """Return a copy of a raw catalog row with the taxonomy fields filled in.

    Only fills fields that are absent, so a row that already specifies (say)
    room_types or seating_capacity is left untouched - future Majlis SKUs can
    declare their own values and they win over these defaults.
    """
    out = dict(entry)
    for key, default in _DEFAULTS.items():
        if key not in out or out[key] is None:
            # copy mutable defaults so callers can't mutate the shared template
            out[key] = list(default) if isinstance(default, list) else default
    if out.get("seating_capacity") is None:
        out["seating_capacity"] = infer_seating_capacity(
            out.get("category", ""), float(out.get("width_cm") or 0.0)
        )
    return out
