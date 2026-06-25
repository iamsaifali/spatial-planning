"""Phase 3: Saudi/Majlis vocabulary + seed catalog readiness.

These prove the catalog now has real Majlis products to recommend, that the new
style tags validate, and that room_type / region / luxury preferences surface and
rank them - all WITHOUT changing living-room behaviour (placement is still the
existing living-room geometry; Majlis perimeter zones are a later phase).
"""

from app.models.preferences import Preferences
from app.models.products import Product
from app.services.recommend.scoring import total_score
from app.services.recommend.selector import select_slots
from app.services.spatial.analyze import analyze_room
from app.services.spatial.zones import zones_for_category

API = "/api/v1"

# A roomy salon so wide Majlis benches actually fit a wall.
MAJLIS_ROOM = {
    "vertices": [[0, 0], [600, 0], [600, 460], [0, 460]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 100}],
    "windows": [],
}


def test_new_style_tags_validate():
    for tag in ("arabic", "saudi_traditional", "majlis", "modern_arabic", "luxury"):
        p = Product(
            id=f"t-{tag}", name="x", brand="b", category="sofa", price=100,
            width_cm=200, depth_cm=90, height_cm=80, style_tags=[tag],
            colors=["Gold"], materials=["Velvet"], delivery_days=7, rating=4.0,
        )
        assert tag in p.style_tags


def test_existing_products_still_validate_after_tag_extension(catalog_repo):
    # legacy products use the original six tags and must still load
    assert len(catalog_repo.all()) == 130  # 100 living-origin + 26 Majlis + 4 beds
    assert len(catalog_repo.in_room_type("majlis")) == 26
    # the 100 living-room-origin products still load (bedroom re-tag only ADDED a room_type)
    assert len([p for p in catalog_repo.all() if "living_room" in p.room_types]) == 100


def test_majlis_products_loaded(catalog_repo):
    majlis = catalog_repo.in_room_type("majlis")
    assert len(majlis) == 26
    cats = {p.category for p in majlis}
    # seed spans seating, surfaces, soft furnishings, storage, decor and lighting
    assert {"sofa", "rug", "coffee_table", "lighting", "decor", "storage"} <= cats
    # every Majlis product carries the foundational taxonomy
    for p in majlis:
        assert p.region in ("saudi_arabia", "gcc")
        assert p.formality == "formal"
        assert p.luxury_tier in ("premium", "luxury")
        assert any(t in p.style_tags for t in ("majlis", "arabic", "saudi_traditional", "modern_arabic"))


def test_majlis_seating_has_capacity(catalog_repo):
    seating = [p for p in catalog_repo.in_room_type("majlis") if p.category in ("sofa", "accent_chair")]
    assert seating and all(p.seating_capacity >= 1 for p in seating)
    benches = [p for p in seating if p.category == "sofa"]
    assert any(p.seating_capacity >= 3 for p in benches)  # long majlis benches


def test_room_type_majlis_returns_majlis_products(catalog_repo):
    analysis = analyze_room(_room())
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    r = select_slots("sofa", zones, Preferences(room_type="majlis"), [], catalog_repo)
    assert r.best is not None
    assert "majlis" in r.best.product.room_types


def test_default_flow_excludes_majlis(catalog_repo):
    # without a room_type, the living-room world is unchanged (no Majlis leakage)
    analysis = analyze_room(_room())
    zones = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())
    r = select_slots("sofa", zones, Preferences(), [], catalog_repo)
    assert r.best is not None
    assert "majlis" not in r.best.product.room_types


def test_region_prefers_gcc_and_saudi(catalog_repo):
    # gcc / saudi products outrank a global item for a Saudi request, all else equal
    analysis = analyze_room(_room())
    zone = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())[0]
    prefs = Preferences(region="saudi_arabia")

    def base(**over):
        return Product(
            id="p", name="x", brand="b", category="sofa", price=500, width_cm=240,
            depth_cm=90, height_cm=80, style_tags=["majlis"], colors=["Gold"],
            materials=["Velvet"], delivery_days=10, rating=4.6, **over,
        )

    saudi = total_score(base(region="saudi_arabia"), zone, prefs, [], catalog_repo)[0]
    gcc = total_score(base(region="gcc"), zone, prefs, [], catalog_repo)[0]
    glob = total_score(base(region="global"), zone, prefs, [], catalog_repo)[0]
    assert saudi >= gcc > glob


def test_luxury_preference_ranks_luxury_majlis_higher(catalog_repo):
    analysis = analyze_room(_room())
    zone = zones_for_category("sofa", analysis, [], catalog_repo.category_stats())[0]
    prefs = Preferences(room_type="majlis", luxury_tier="luxury")

    def base(**over):
        return Product(
            id="p", name="x", brand="b", category="sofa", price=1200, width_cm=240,
            depth_cm=90, height_cm=80, style_tags=["majlis"], colors=["Gold"],
            materials=["Velvet"], delivery_days=10, rating=4.6, region="gcc", **over,
        )

    lux = total_score(base(luxury_tier="luxury"), zone, prefs, [], catalog_repo)[0]
    prem = total_score(base(luxury_tier="premium"), zone, prefs, [], catalog_repo)[0]
    assert lux > prem


def test_majlis_products_browsable_via_api(client):
    r = client.get(f"{API}/products", params={"room_type": "majlis"})
    assert r.status_code == 200 and r.json()["total"] == 26
    r = client.get(f"{API}/products", params={"style": "majlis"})
    assert r.status_code == 200 and r.json()["total"] >= 20
    r = client.get(f"{API}/products", params={"region": "gcc"})
    assert r.status_code == 200 and r.json()["total"] == 16


def _room():
    from app.models.geometry import Room

    return Room.model_validate(MAJLIS_ROOM)
