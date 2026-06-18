"""Preference-driven layout planning: catalog pool, director fallback, endpoints."""

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


# --- capacity maths ----------------------------------------------------------

def test_capacity_helpers():
    assert capacity.target_capacity(Preferences(seating_capacity=6)) == 6
    assert capacity.target_capacity(Preferences(room_purpose="entertaining")) == 6
    assert capacity.extra_seats_as_chairs(Preferences(seating_capacity=6)) == 3  # 6 - 3-seat sofa
    assert capacity.extra_seats_as_chairs(Preferences(seating_capacity=2)) == 0
    assert capacity.extra_seats_as_chairs(Preferences(seating_capacity=12)) == 4  # capped at 4


# --- deterministic fallback plan (no LLM) ------------------------------------

def test_fallback_plan_is_deterministic_and_sofa_first(catalog_repo, rect_room):
    prefs = Preferences(room_purpose="entertaining", seating_capacity=6, styles=["boho"])
    analysis = analyze_room(rect_room)
    summary = catalog_repo.category_summary(prefs)
    p1 = director.fallback_plan(prefs, analysis, summary)
    p2 = director.fallback_plan(prefs, analysis, summary)
    assert p1.model_dump() == p2.model_dump()
    cats = [i.category for i in p1.items]
    assert cats and cats[0] == "sofa"
    assert "accent_chair" in cats
    chair = next(i for i in p1.items if i.category == "accent_chair")
    assert chair.quantity == 2  # 6 seats - 3-seat sofa -> 2 chairs
    for item in p1.items:
        assert item.quantity <= archetypes.QUANTITY_CAPS[item.category]


def test_style_drops_categories(catalog_repo, rect_room):
    prefs = Preferences(room_purpose="family", styles=["minimal"])
    analysis = analyze_room(rect_room)
    summary = catalog_repo.category_summary(prefs)
    cats = [i.category for i in director.fallback_plan(prefs, analysis, summary).items]
    assert "sofa" in cats
    assert "decor" not in cats and "side_table" not in cats  # minimal drops these


# --- LLM-output coercion / validation ----------------------------------------

def test_coerce_plan_drops_and_clamps(catalog_repo, rect_room):
    analysis = analyze_room(rect_room)
    summary = catalog_repo.category_summary(Preferences())
    data = {
        "archetype": "x",
        "rationale": "y",
        "items": [
            {"category": "sofa", "quantity": 5, "anchor": "on_focal_wall", "anchor_ref": "focal_wall"},
            {"category": "bathtub", "quantity": 1, "anchor": "center", "anchor_ref": "room"},
            {"category": "tv_unit", "quantity": 1, "anchor": "levitate", "anchor_ref": "sofa"},
        ],
    }
    plan = director._coerce_plan(data, summary, analysis)
    cats = [i.category for i in plan.items]
    assert "bathtub" not in cats            # off-vocab category dropped
    assert cats[0] == "sofa"                # dependency order
    sofa = next(i for i in plan.items if i.category == "sofa")
    assert sofa.quantity == 1               # clamped from 5 to cap
    tv = next(i for i in plan.items if i.category == "tv_unit")
    assert tv.anchor in director._VALID_ANCHORS  # off-vocab anchor replaced


def test_resolve_anchor_demotes_unavailable_geometry():
    class _Stub:
        focal_wall_index = None
        window_strips: dict = {}

    assert director._resolve_anchor("sofa", "on_focal_wall", "focal_wall", _Stub()) == ("center", "room")


# --- endpoints (client has no OpenAI key -> heuristic fallback) --------------

def test_plan_endpoint(client):
    r = client.post(f"{API}/guide/plan", json={"room": ROOM, "placed_items": []})
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["items"] and body["plan_source"] == "template"
    cats = [i["category"] for i in body["plan"]["items"]]
    assert cats[0] == "sofa"
    assert body["steps"] and body["steps"][0]["status"] == "current"


def test_plan_respects_preferences(client):
    r = client.post(
        f"{API}/guide/plan",
        json={"room": ROOM, "preferences": {"room_purpose": "family", "styles": ["minimal"]}, "placed_items": []},
    )
    cats = [i["category"] for i in r.json()["plan"]["items"]]
    assert "sofa" in cats and "decor" not in cats and "side_table" not in cats


def test_step_quantity_comes_from_plan(client):
    r = client.post(
        f"{API}/guide/step/side_table",
        json={"room": ROOM, "preferences": {"room_purpose": "family"}, "placed_items": []},
    )
    assert r.status_code == 200
    assert r.json()["quantity"] == 2  # 17 m2 room -> pair of side tables


# --- large room: scaling + enough decor spots --------------------------------

def test_large_room_scales_and_has_decor_spots(catalog_repo):
    from app.models.geometry import PlacedItem, Room
    from app.services.spatial.zones import anchor_pose, zones_for_category

    big = Room(
        vertices=[(0, 0), (950, 0), (950, 770), (0, 770)],
        doors=[{"id": "d1", "wall_index": 0, "offset_cm": 60, "width_cm": 90}],
    )
    analysis = analyze_room(big)
    prefs = Preferences(room_purpose="entertaining", seating_capacity=6)
    summary = catalog_repo.category_summary(prefs)

    q = {i.category: i.quantity for i in director.fallback_plan(prefs, analysis, summary).items}
    assert q.get("decor", 0) >= 3          # big room -> more decor (was effectively 1)
    assert q.get("lighting", 0) >= 2
    assert q.get("accent_chair", 0) >= 2

    # the "No good fit" decor bug: a big room must offer >= 3 distinct decor spots
    stats = catalog_repo.category_stats()
    sofa = catalog_repo.in_category("sofa")[0]
    sz = zones_for_category("sofa", analysis, [], stats)
    pose = anchor_pose(sz[0], sofa, analysis)
    placed = [(PlacedItem(instance_id="s1", product_id=sofa.id, x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg), sofa)]
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
