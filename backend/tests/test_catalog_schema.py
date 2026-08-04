"""Catalog schema + backfill: room_types default + seating-capacity inference.

These fields are additive and must not change geometry, rendering, or existing
living-room recommendations - only carry room-type intent.
"""

import pytest

from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import Product
from spatial_planning.services.catalog.backfill import backfill_product, infer_seating_capacity

API = "/api/v1"


def _raw(**over) -> dict:
    """A legacy-shaped catalog row (no room_types), as in catalog.json."""
    base = {
        "id": "x-1",
        "name": "Test Sofa",
        "category": "sofa",
        "price": 500,
        "width_cm": 220,
        "depth_cm": 90,
        "height_cm": 80,
        "style_tags": ["modern"],
        "colors": ["Ivory"],
    }
    base.update(over)
    return base


# --- backfill / migration ---------------------------------------------------------


def test_backfill_fills_default_room_types_for_legacy_row():
    out = backfill_product(_raw())
    assert out["room_types"] == ["living_room"]


def test_backfill_infers_seating_capacity_from_width():
    assert backfill_product(_raw(category="sofa", width_cm=220))["seating_capacity"] == 3
    assert backfill_product(_raw(category="sofa", width_cm=160))["seating_capacity"] == 2
    assert backfill_product(_raw(category="accent_chair", width_cm=70))["seating_capacity"] == 1
    # non-seating categories get 0
    assert backfill_product(_raw(category="rug", width_cm=300))["seating_capacity"] == 0
    assert backfill_product(_raw(category="tv_unit", width_cm=180))["seating_capacity"] == 0


def test_infer_seating_capacity_units():
    assert infer_seating_capacity("sofa", 75) == 1
    assert infer_seating_capacity("majlis_sofa", 240) == 3  # future category, scales by width
    assert infer_seating_capacity("floor_cushion", 60) == 1
    assert infer_seating_capacity("storage", 120) == 0


def test_backfill_does_not_override_explicit_values():
    out = backfill_product(_raw(room_types=["majlis"], seating_capacity=8))
    assert out["room_types"] == ["majlis"]
    assert out["seating_capacity"] == 8


def test_backfill_is_pure_no_shared_mutable_default():
    a = backfill_product(_raw(id="a"))
    b = backfill_product(_raw(id="b"))
    a["room_types"].append("majlis")
    assert b["room_types"] == ["living_room"]  # not aliased to a's list


# --- model accepts both legacy and new shapes -------------------------------------


def test_product_defaults_when_constructed_without_room_types():
    p = Product(**_raw())
    assert p.room_types == ["living_room"]
    assert p.seating_capacity == 0  # model default; loader backfills inferred values


def test_product_accepts_explicit_room_types():
    p = Product(**_raw(id="majlis-sofa-001", category="sofa",
                       room_types=["majlis", "living_room"], seating_capacity=3))
    assert p.room_types == ["majlis", "living_room"]
    assert p.seating_capacity == 3


def test_product_rejects_removed_metadata_fields():
    # the taxonomy / commerce metadata fields were removed from the model (extra=forbid),
    # so a stray legacy key must be rejected rather than silently carried.
    with pytest.raises(Exception):
        Product(**_raw(region="mars"))
    with pytest.raises(Exception):
        Product(**_raw(brand="Acme"))


# --- preferences ------------------------------------------------------------------


def test_preferences_optional_fields_default_none():
    p = Preferences()
    assert p.room_type is None and p.seating_capacity is None


def test_preferences_accepts_room_type_and_seating():
    p = Preferences(styles=["modern"], room_type="bedroom", seating_capacity=10)
    assert p.room_type == "bedroom"
    assert p.seating_capacity == 10


# --- loaded catalog + repository filtering ----------------------------------------


def test_loaded_catalog_is_backfilled(catalog_repo):
    # 100 living-room-origin + 26 Majlis seed + 4 bedroom beds = 130
    products = catalog_repo.all()
    assert len(products) == 130
    living = [p for p in products if "living_room" in p.room_types and p.category != "bed"]
    assert len(living) == 100
    # seating inference still holds across the legacy living-room catalog
    legacy_sofas = [p for p in catalog_repo.in_category("sofa") if "majlis" not in p.room_types]
    assert legacy_sofas and all(s.seating_capacity >= 1 for s in legacy_sofas)
    assert all(t.seating_capacity == 0 for t in catalog_repo.in_category("tv_unit"))


def test_repository_room_type_filters(catalog_repo):
    # re-tagging kept living_room (so the count is unchanged at 100); beds are bedroom-only.
    assert len(catalog_repo.in_room_type("living_room")) == 100
    assert len(catalog_repo.in_room_type("majlis")) == 26
    assert len(catalog_repo.in_room_type("bedroom")) == 27  # 4 beds + 23 re-tagged

    _items, total = catalog_repo.search(room_type="living_room")
    assert total == 100
