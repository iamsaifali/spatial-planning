"""Preference-driven layout planning: catalog pool, LLM-only director, endpoints."""

from app.models.preferences import Preferences
from app.services.plan import archetypes, capacity, director
from app.services.spatial.analyze import analyze_room

API = "/api/v1"

ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
}

CATEGORIES = ["sofa", "tv_unit", "rug", "coffee_table", "side_table", "accent_chair", "lighting", "storage", "decor"]


# --- catalog pool + summary --------------------------------------------------

def test_pool_for_never_empty(catalog_repo):
    prefs = Preferences(styles=["modern"], colors=["Oak"])
    for cat in CATEGORIES:
        assert catalog_repo.pool_for(cat, prefs), f"{cat} pool should never be empty"


def test_pool_for_best_match_first(catalog_repo):
    sofas = catalog_repo.pool_for("sofa", Preferences(styles=["modern"]))
    is_match = ["modern" in p.style_tags for p in sofas]
    if any(is_match) and not all(is_match):
        assert is_match.index(True) < is_match.index(False)


def test_category_summary_exposes_no_products(catalog_repo):
    summary = catalog_repo.category_summary(Preferences(styles=["modern"], colors=["Oak"]))
    assert "sofa" in summary and "custom" not in summary
    sofa = summary["sofa"]
    assert set(sofa.keys()) == {"count", "price_min", "price_max", "has_style_match", "has_colour_match"}
    assert sofa["count"] > 0 and sofa["price_min"] <= sofa["price_max"]


# --- deterministic knowledge tables (still own the plan's content bounds) -----

def test_capacity_helpers():
    assert capacity.target_capacity(Preferences(seating_capacity=6)) == 6
    assert capacity.target_capacity(Preferences(room_purpose="entertaining")) == 6
    assert capacity.target_capacity(Preferences(room_purpose="family")) == 4


def test_candidate_categories_drops_by_style():
    cats = archetypes.candidate_categories(Preferences(room_purpose="family", styles=["minimal"]))
    assert "sofa" in cats
    assert "decor" not in cats and "side_table" not in cats  # minimal drops these


def test_caps_scale_with_area():
    small = archetypes.caps_for(15.0)
    big = archetypes.caps_for(40.0)
    assert big["accent_chair"] > small["accent_chair"]
    assert big["decor"] >= small["decor"]
    # sofas scale for L/U seating only in larger rooms; tiny rooms stay single
    assert small["sofa"] == 1 and big["sofa"] >= 2


# --- LLM-output coercion / validation (pure, no LLM) -------------------------

def test_coerce_plan_drops_clamps_and_tiers(catalog_repo, rect_room):
    analysis = analyze_room(rect_room)
    summary = catalog_repo.category_summary(Preferences())
    data = {
        "archetype": "family",
        "rationale": "y",
        "items": [
            {"category": "sofa", "quantity": 5, "priority": 1, "tier": "non_essential"},
            {"category": "bathtub", "quantity": 1, "priority": 2, "tier": "essential"},
            {"category": "decor", "quantity": 2, "priority": 9, "tier": "non_essential"},
        ],
    }
    plan = director._coerce_plan(data, summary, analysis)
    cats = [i.category for i in plan.items]
    assert "bathtub" not in cats                       # off-vocab category dropped
    assert cats[0] == "sofa"                            # dependency order
    sofa = next(i for i in plan.items if i.category == "sofa")
    assert sofa.quantity == 1                           # clamped from 5 to cap
    assert sofa.tier == "essential"                     # essential pinned, overriding the LLM
    decor = next(i for i in plan.items if i.category == "decor")
    assert decor.tier == "non_essential"                # non-essential tier preserved
    # essentials guaranteed present even though the LLM only sent sofa + decor
    assert {"sofa", "tv_unit", "rug", "coffee_table"} <= set(cats)


# --- endpoints: planning is LLM-only (no second path) ------------------------

def test_plan_endpoint_uses_llm(client, llm_plan):
    r = client.post(f"{API}/guide/plan", json={"room": ROOM, "placed_items": []})
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["items"] and body["plan_source"] == "llm"
    cats = [i["category"] for i in body["plan"]["items"]]
    assert cats[0] == "sofa"
    assert body["steps"] and body["steps"][0]["status"] == "current"


def test_plan_requires_llm(client):
    """With no API key and no fallback, planning surfaces a clear error."""
    r = client.post(f"{API}/guide/plan", json={"room": ROOM, "placed_items": []})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "PLAN_UNAVAILABLE"


def test_step_quantity_comes_from_plan(client, llm_plan):
    r = client.post(
        f"{API}/guide/step/side_table",
        json={"room": ROOM, "preferences": {"room_purpose": "family"}, "placed_items": []},
    )
    assert r.status_code == 200
    assert r.json()["quantity"] == 2  # canned plan -> a pair of side tables


def test_multi_sofa_flow_end_to_end(client, monkeypatch):
    """A high-capacity plan in a big room drives 2nd/3rd sofas onto perpendicular walls
    through the real /guide endpoints (plan -> step -> place -> re-step)."""
    big = {
        "vertices": [[0, 0], [700, 0], [700, 600], [0, 600]],  # 42 m^2 -> sofa cap 3
        "doors": [{"id": "d", "wall_index": 0, "offset_cm": 60, "width_cm": 90}],
    }
    plan = {
        "archetype": "family", "rationale": "x",
        "items": [{"category": "sofa", "quantity": 3, "priority": 1, "tier": "essential"}],
    }

    async def _fake(kind, facts, instruction):
        return {**plan} if kind == "layout_plan" else None

    from app.services.ai import copy_service
    from app.services.plan import director
    monkeypatch.setattr(copy_service, "_llm_generate", _fake)
    director.clear_cache()
    prefs = {"room_purpose": "family", "seating_capacity": 8}

    # plan: sofa stays current with quantity 3 (not clamped to 1)
    r = client.post(f"{API}/guide/plan", json={"room": big, "preferences": prefs, "placed_items": []})
    assert r.status_code == 200
    sofa_step = next(s for s in r.json()["steps"] if s["category"] == "sofa")
    assert sofa_step["quantity"] == 3 and sofa_step["status"] == "current"

    # sofa #1: primary zone + a recommendation we can "place"
    r = client.post(f"{API}/guide/step/sofa", json={"room": big, "preferences": prefs, "placed_items": []})
    assert r.status_code == 200 and r.json()["zones"]
    rec = r.json()["recommendations"][0]
    pose1 = rec["suggested_pose"]
    placed1 = [{"instance_id": "s1", "product_id": rec["product"]["id"], **pose1}]

    # sofa #2: with one placed, the step must offer a perpendicular L-return zone
    r = client.post(f"{API}/guide/step/sofa", json={"room": big, "preferences": prefs, "placed_items": placed1})
    assert r.status_code == 200
    z2 = r.json()["zones"]
    assert z2, "expected an L-return zone for the 2nd sofa"
    d = abs((z2[0]["suggested_rotation_deg"] - pose1["rotation_deg"]) % 180)
    assert 60 < d < 120, f"2nd sofa zone should be perpendicular to the 1st (got {d})"


def test_step_degrades_without_plan(client):
    """The step endpoint still serves recommendations when planning is unavailable."""
    r = client.post(f"{API}/guide/step/sofa", json={"room": ROOM, "placed_items": []})
    assert r.status_code == 200
    body = r.json()
    assert body["quantity"] == 1                       # no plan -> default quantity
    assert 1 <= len(body["recommendations"]) <= 5      # recommendations don't need the LLM


# --- large-room geometry: enough distinct zone spots (unchanged engine) ------

def test_large_room_has_decor_spots(catalog_repo):
    from app.models.geometry import PlacedItem, Room
    from app.services.spatial.zones import anchor_pose, zones_for_category

    big = Room(
        vertices=[(0, 0), (950, 0), (950, 770), (0, 770)],
        doors=[{"id": "d1", "wall_index": 0, "offset_cm": 60, "width_cm": 90}],
    )
    analysis = analyze_room(big)
    stats = catalog_repo.category_stats()
    sofa = catalog_repo.in_category("sofa")[0]
    sz = zones_for_category("sofa", analysis, [], stats)
    pose = anchor_pose(sz[0], sofa, analysis)
    placed = [(PlacedItem(instance_id="s1", product_id=sofa.id, x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg), sofa)]
    # a big room must offer >= 3 distinct decor spots (the "No good fit" decor bug)
    assert len(zones_for_category("decor", analysis, placed, stats)) >= 3


def test_big_room_floats_sofa_small_room_does_not(catalog_repo):
    from app.models.geometry import Room
    from app.services.spatial.zones import zones_for_category

    stats = catalog_repo.category_stats()
    big = analyze_room(Room(vertices=[(0, 0), (820, 0), (820, 870), (0, 870)],
                            doors=[{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": 90}]))
    small = analyze_room(Room(vertices=[(0, 0), (480, 0), (480, 360), (0, 360)],
                              doors=[{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": 90}]))
    big_zone = zones_for_category("sofa", big, [], stats)[0]
    small_zone = zones_for_category("sofa", small, [], stats)[0]
    assert big_zone.float_cm > 150   # big room floats the sofa inward for viewing distance
    assert small_zone.float_cm == 0.0  # small room keeps the sofa against the wall
