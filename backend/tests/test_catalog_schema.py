"""Foundational taxonomy schema + catalog backfill (Saudi/Majlis groundwork).

These fields are additive and must not change geometry, rendering, or existing
living-room recommendations - only carry intent for future room-type support.
"""

import pytest

from app.models.preferences import Preferences
from app.models.products import Product
from app.services.catalog.backfill import backfill_product, infer_seating_capacity

API = "/api/v1"


def _raw(**over) -> dict:
    """A legacy-shaped catalog row (no taxonomy fields), as in catalog.json."""
    base = {
        "id": "x-1",
        "name": "Test Sofa",
        "brand": "Acme",
        "category": "sofa",
        "price": 500,
        "width_cm": 220,
        "depth_cm": 90,
        "height_cm": 80,
        "style_tags": ["modern"],
        "colors": ["Ivory"],
        "materials": ["Linen"],
        "delivery_days": 5,
        "rating": 4.2,
    }
    base.update(over)
    return base


# --- backfill / migration ---------------------------------------------------------


def test_backfill_fills_defaults_for_legacy_row():
    out = backfill_product(_raw())
    assert out["room_types"] == ["living_room"]
    assert out["placement_type"] == "wall_hug"
    assert out["region"] == "global"
    assert out["formality"] == "family"
    assert out["luxury_tier"] == "standard"
    assert out["is_modular"] is False


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
    out = backfill_product(_raw(room_types=["majlis"], seating_capacity=8, region="saudi_arabia"))
    assert out["room_types"] == ["majlis"]
    assert out["seating_capacity"] == 8
    assert out["region"] == "saudi_arabia"


def test_backfill_is_pure_no_shared_mutable_default():
    a = backfill_product(_raw(id="a"))
    b = backfill_product(_raw(id="b"))
    a["room_types"].append("majlis")
    assert b["room_types"] == ["living_room"]  # not aliased to a's list


# --- model accepts both legacy and new shapes -------------------------------------


def test_product_defaults_when_constructed_without_taxonomy():
    p = Product(**_raw())
    assert p.room_types == ["living_room"]
    assert p.placement_type == "wall_hug"
    assert p.region == "global"
    assert p.seating_capacity == 0  # model default; loader backfills inferred values


def test_product_accepts_full_majlis_taxonomy():
    p = Product(
        **_raw(
            id="majlis-sofa-001",
            category="sofa",
            room_types=["majlis", "living_room"],
            placement_type="perimeter",
            seating_capacity=3,
            is_modular=True,
            formality="formal",
            luxury_tier="luxury",
            region="saudi_arabia",
        )
    )
    assert p.placement_type == "perimeter"
    assert p.luxury_tier == "luxury"
    assert p.is_modular is True


def test_product_rejects_unknown_enum_values():
    with pytest.raises(Exception):
        Product(**_raw(region="mars"))
    with pytest.raises(Exception):
        Product(**_raw(luxury_tier="diamond"))


# --- preferences ------------------------------------------------------------------


def test_preferences_new_fields_optional_and_default_none():
    p = Preferences()
    assert p.room_type is None and p.region is None and p.seating_capacity is None
    assert p.formality is None and p.luxury_tier is None and p.materials == []


def test_preferences_accepts_new_fields():
    p = Preferences(
        styles=["modern"],
        room_type="majlis",
        region="saudi_arabia",
        seating_capacity=10,
        formality="formal",
        luxury_tier="luxury",
        materials=["Velvet", "Carved Wood"],
    )
    assert p.room_type == "majlis"
    assert p.seating_capacity == 10
    assert p.materials == ["Velvet", "Carved Wood"]


# --- loaded catalog + repository filtering ----------------------------------------


def test_loaded_catalog_is_backfilled(catalog_repo):
    # 100 living-room-origin + 26 Majlis seed + 4 bedroom beds = 130
    products = catalog_repo.all()
    assert len(products) == 130
    # the original living-room cohort keeps its backfilled region/placement defaults
    # (bedroom re-tagging only added a room_type; it changed no other field)
    living = [p for p in products if "living_room" in p.room_types and p.category != "bed"]
    assert len(living) == 100
    for p in living:
        assert p.region == "global"
        assert p.placement_type == "wall_hug"
    # seating inference still holds across the legacy living-room catalog
    legacy_sofas = [p for p in catalog_repo.in_category("sofa") if "majlis" not in p.room_types]
    assert legacy_sofas and all(s.seating_capacity >= 1 for s in legacy_sofas)
    assert all(t.seating_capacity == 0 for t in catalog_repo.in_category("tv_unit"))


def test_repository_room_type_and_region_filters(catalog_repo):
    # re-tagging kept living_room (so the count is unchanged at 100); beds are bedroom-only.
    assert len(catalog_repo.in_room_type("living_room")) == 100
    assert len(catalog_repo.in_room_type("majlis")) == 26
    assert len(catalog_repo.in_room_type("bedroom")) == 27  # 4 beds + 23 re-tagged

    items, total = catalog_repo.search(room_type="living_room")
    assert total == 100
    items, total = catalog_repo.search(region="saudi_arabia")
    assert total == 10  # Majlis seed adds Saudi-origin products
    items, total = catalog_repo.search(luxury_tier="standard")
    assert total == 102  # 100 living-origin standard + 2 standard beds


def test_products_api_supports_new_filters(client):
    # all sofas: 16 living-room + 6 Majlis = 22
    r = client.get(f"{API}/products", params={"category": "sofa"})
    assert r.status_code == 200 and r.json()["total"] == 22
    # room_type filter excludes Majlis-only sofas -> back to the 16 living-room sofas
    r = client.get(f"{API}/products", params={"room_type": "living_room", "category": "sofa"})
    assert r.status_code == 200 and r.json()["total"] == 16
    r = client.get(f"{API}/products", params={"region": "saudi_arabia"})
    assert r.status_code == 200 and r.json()["total"] == 10


def test_existing_living_room_recommendation_still_works(client):
    """Guard: the new fields must not change living-room recommendations."""
    room = {
        "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
        "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90}],
        "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
    }
    r = client.post(f"{API}/guide/step/sofa", json={"room": room, "placed_items": []})
    assert r.status_code == 200
    assert len(r.json()["recommendations"]) == 3
