"""Style / colour metadata FILTERING in select_slots (filter-when-available).

The fixture catalog carries no style/main_family, so these use small hand-built repos whose products
differ ONLY in style/main_family - proving the preference (not the deterministic id tiebreak) is what
steers selection, and that an unmatched preference falls back instead of leaving a piece unplaceable.
"""

from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import Product
from spatial_planning.services.catalog.repository import CatalogRepository
from spatial_planning.services.recommend.selector import select_slots
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.zones import zones_for_category


def _sofa(pid: str, styles: list[str], family: str):
    return Product(
        id=pid, name=pid, brand="Test", category="3-seater-sofa",
        price=1000, width_cm=200, depth_cm=90, height_cm=85,
        style_tags=["modern"], colors=["Beige"], materials=[],
        delivery_days=7, rating=4.0, room_types=["living_room"], seating_capacity=3,
        styles=styles, main_color="X", secondary_colors=[], main_family=family,
    )


def _sofa_zones(rect_room, repo):
    analysis = analyze_room(rect_room)
    return zones_for_category("sofa", analysis, [], repo.category_stats())


def test_style_filter_prefers_matching_style(rect_room):
    # "boho_earth" sorts first by id, so it would win WITHOUT the filter; style=Modern must flip it.
    repo = CatalogRepository([_sofa("boho_earth", ["Boho"], "Earthy/Terracotta"),
                              _sofa("modern_wood", ["Modern"], "Wood/Natural")])
    r = select_slots("sofa", _sofa_zones(rect_room, repo), Preferences(style="Modern"), [], repo)
    assert r.best.product.id == "modern_wood"


def test_color_family_filter_prefers_matching_family(rect_room):
    repo = CatalogRepository([_sofa("aaa_blue", ["Modern"], "Blue"),
                              _sofa("zzz_wood", ["Modern"], "Wood/Natural")])
    r = select_slots("sofa", _sofa_zones(rect_room, repo), Preferences(color_families=["Wood/Natural"]), [], repo)
    assert r.best.product.id == "zzz_wood"


def test_color_applies_within_style_matched_set(rect_room):
    repo = CatalogRepository([_sofa("modern_wood", ["Modern"], "Wood/Natural"),
                              _sofa("modern_blue", ["Modern"], "Blue"),
                              _sofa("boho_wood", ["Boho"], "Wood/Natural")])
    r = select_slots("sofa", _sofa_zones(rect_room, repo),
                     Preferences(style="Modern", color_families=["Wood/Natural"]), [], repo)
    assert r.best.product.id == "modern_wood"


def test_unmatched_preference_falls_back(rect_room):
    # nothing is Zen / Jewel Tones -> the filter must NOT empty the pool.
    repo = CatalogRepository([_sofa("boho_earth", ["Boho"], "Earthy/Terracotta"),
                              _sofa("modern_wood", ["Modern"], "Wood/Natural")])
    r = select_slots("sofa", _sofa_zones(rect_room, repo),
                     Preferences(style="Zen", color_families=["Jewel Tones"]), [], repo)
    assert r.best is not None
