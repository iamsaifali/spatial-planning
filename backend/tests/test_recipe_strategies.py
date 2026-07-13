"""Phase 4 - real strategy implementations.

Each named strategy resolves to a real handler that calls the specific geometry
generator directly. These tests prove the handlers produce zones byte-identical to the
legacy zones_for_category dispatch for the (strategy, category) pairs the recipes use,
and that center_area genuinely consumes size params.
"""

import pytest

from spatial_planning.models.geometry import Room
from spatial_planning.services.recipe.registry import get_recipe
from spatial_planning.services.recipe.strategies import STRATEGY_REGISTRY, resolve_strategy
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.strategies import SPATIAL_STRATEGIES, center_area
from spatial_planning.services.spatial.zones import zones_for_category

RECT = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
}
WIDE = {
    "vertices": [[0, 0], [600, 0], [600, 560], [0, 560]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 250, "width_cm": 100}],
    "windows": [],
}


def _sig(zones):
    """Structural signature of a zone list (id, polygon, reason codes, rotation, ...)."""
    return [z.to_model().model_dump() for z in zones]


# --- handlers resolve independently ------------------------------------------------


def test_every_strategy_resolves_to_a_callable_handler():
    assert set(STRATEGY_REGISTRY) == set(SPATIAL_STRATEGIES)
    for name in STRATEGY_REGISTRY:
        assert callable(resolve_strategy(name).resolver)


def test_unknown_strategy_fails_clearly():
    with pytest.raises(KeyError, match="nope"):
        resolve_strategy("nope")


def test_handlers_return_zone_lists(catalog_repo):
    analysis = analyze_room(Room.model_validate(WIDE))
    stats = catalog_repo.category_stats()
    # a couple of representative handlers run end-to-end and yield zones
    assert isinstance(resolve_strategy("perimeter_walls").resolver("sofa", "majlis", analysis, [], stats, {}), list)
    assert isinstance(resolve_strategy("center_area").resolver("rug", "majlis", analysis, [], stats, {}), list)


# --- zones match the legacy dispatch ----------------------------------------------


def _assert_roles_match_legacy(room_spec, room_type, repo):
    analysis = analyze_room(Room.model_validate(room_spec))
    stats = repo.category_stats()
    for role in get_recipe(room_type).roles:
        # Some strategies are intentionally BEYOND the legacy planner (no legacy dispatch
        # equivalent), so they are exempt from the equivalence check: l_return (big-room
        # L-return sofa), on_surface (accents resting on a surface, e.g. vases on a console).
        if role.zone_strategy.name in ("l_return", "on_surface"):
            continue
        category = role.categories[0]
        strat = resolve_strategy(role.zone_strategy.name)
        via_strategy = strat.resolver(category, room_type, analysis, [], stats, role.zone_strategy.params)
        via_legacy = zones_for_category(category, analysis, [], stats, room_type=room_type)
        assert _sig(via_strategy) == _sig(via_legacy), (room_type, role.role, role.zone_strategy.name, category)


def test_living_room_strategy_zones_match_legacy(catalog_repo):
    _assert_roles_match_legacy(RECT, "living_room", catalog_repo)


def test_majlis_strategy_zones_match_legacy(catalog_repo):
    _assert_roles_match_legacy(WIDE, "majlis", catalog_repo)


def test_perimeter_walls_matches_legacy_majlis_sofa(catalog_repo):
    analysis = analyze_room(Room.model_validate(WIDE))
    stats = catalog_repo.category_stats()
    via_strategy = resolve_strategy("perimeter_walls").resolver("sofa", "majlis", analysis, [], stats, {})
    via_legacy = zones_for_category("sofa", analysis, [], stats, room_type="majlis")
    assert _sig(via_strategy) == _sig(via_legacy)
    # and it is genuinely the perimeter (not the living-room sofa) behaviour
    assert via_strategy and all("majlis_perimeter_seating" in z.reason_codes for z in via_strategy)


def test_center_area_matches_legacy_rug_and_table(catalog_repo):
    analysis = analyze_room(Room.model_validate(WIDE))
    stats = catalog_repo.category_stats()
    for category in ("rug", "coffee_table"):
        via_strategy = resolve_strategy("center_area").resolver(category, "majlis", analysis, [], stats, {})
        via_legacy = zones_for_category(category, analysis, [], stats, room_type="majlis")
        assert _sig(via_strategy) == _sig(via_legacy), category


# --- param consumption -------------------------------------------------------------


def test_center_area_consumes_size_params(catalog_repo):
    analysis = analyze_room(Room.model_validate(WIDE))
    stats = catalog_repo.category_stats()

    default = center_area("coffee_table", "majlis", analysis, [], stats, {})
    explicit = center_area("coffee_table", "majlis", analysis, [], stats, {"size_w": 140, "size_d": 120})
    bigger = center_area("coffee_table", "majlis", analysis, [], stats, {"size_w": 400, "size_d": 400})

    # explicit defaults reproduce the implicit (legacy) sizing
    assert _sig(default) == _sig(explicit)
    assert _sig(default) == _sig(zones_for_category("coffee_table", analysis, [], stats, room_type="majlis"))
    # a larger size genuinely flows into the geometry -> a different zone
    assert _sig(default) != _sig(bigger)
