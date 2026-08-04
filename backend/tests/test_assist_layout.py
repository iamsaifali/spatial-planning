"""POST /assist/layout - deterministic whole-room auto-planner (now returns templates)."""

from spatial_planning.config import get_settings
from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.validation import MUST_FIX_CODES
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.validate import validate_item

API = "/api/v1"

ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 180, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 150, "width_cm": 160}],
}
PREFS = {"styles": ["modern"]}


def _payload(**over):
    return {"room": ROOM, "placed_items": [], "preferences": PREFS, **over}


def _templates(body):
    return body["templates"]


def _recommended(body):
    """The pre-selected layout (the first/recommended template)."""
    return next(t for t in body["templates"] if t["recommended"])["layout"]


def test_assist_layout_full_room(client):
    r = client.post(f"{API}/assist/layout", json=_payload())
    assert r.status_code == 200
    body = r.json()

    # response is a set of templates; exactly one is the recommendation
    templates = _templates(body)
    assert len(templates) >= 1
    assert sum(1 for t in templates if t["recommended"]) == 1
    assert all(t["label"] for t in templates)

    layout = _recommended(body)
    assert layout["proposal_id"].startswith("lay_")
    assert len(layout["placements"]) >= 3  # criterion: multiple valid placements
    assert layout["totals"]["item_count"] == len(layout["placements"])
    assert layout["totals"]["currency"] == "USD"

    # every placement carries a full product + a deterministic (non-LLM) rationale
    first = layout["placements"][0]
    assert first["category"] == "sofa"  # living-room sequence starts with the sofa
    assert first["product"]["id"] == first["product_id"]
    assert first["rationale"]
    assert layout["skipped"] == [] or all("reason" in s for s in layout["skipped"])


def test_assist_layout_returns_distinct_named_templates(client):
    # A living room offers position templates, each a distinct VALID layout. Templates with a
    # misaligned TV / floating L / warning are dropped, so a constrained room (e.g. a centred
    # door blocking the opposite walls) may legitimately surface just one good option.
    body = client.post(f"{API}/assist/layout", json=_payload()).json()
    templates = _templates(body)
    assert len(templates) >= 1
    ids = [t["layout"]["proposal_id"] for t in templates]
    assert len(set(ids)) == len(ids)  # genuinely different arrangements
    assert len({t["label"] for t in templates}) == len(templates)  # unique names
    for t in templates:  # every option is gate-valid
        assert not [f for f in t["layout"]["findings"] if f["severity"] == "error"]


def test_assist_layout_placements_have_no_hard_errors(client, catalog_repo):
    from spatial_planning.models.geometry import Room

    body = client.post(f"{API}/assist/layout", json=_payload()).json()
    room = Room.model_validate(ROOM)
    analysis = analyze_room(room)

    for tmpl in _templates(body):  # check EVERY template, not just one
        placed: list[tuple[PlacedItem, object]] = []
        for p in tmpl["layout"]["placements"]:
            item = PlacedItem(
                instance_id=p["instance_id"],
                product_id=p["product_id"],
                x=p["pose"]["x"],
                y=p["pose"]["y"],
                rotation_deg=p["pose"]["rotation_deg"],
            )
            product = catalog_repo.require(p["product_id"])
            findings = validate_item(analysis, placed, item, product)
            assert not [f for f in findings if f.code in MUST_FIX_CODES], (tmpl["label"], p["category"], findings)
            placed.append((item, product))


def test_assist_layout_is_deterministic(client):
    a = client.post(f"{API}/assist/layout", json=_payload()).json()
    b = client.post(f"{API}/assist/layout", json=_payload()).json()
    assert [t["layout"]["proposal_id"] for t in _templates(a)] == [t["layout"]["proposal_id"] for t in _templates(b)]
    assert [t["label"] for t in _templates(a)] == [t["label"] for t in _templates(b)]


def test_assist_layout_respects_existing_items(client):
    # user already placed a sofa - the planner must not add a second one
    sofa = {"instance_id": "mine", "product_id": "sofa-001", "x": 240, "y": 305, "rotation_deg": 180}
    layout = _recommended(client.post(f"{API}/assist/layout", json=_payload(placed_items=[sofa])).json())
    assert "sofa" not in [p["category"] for p in layout["placements"]]
    assert {"category": "sofa", "reason": "ALREADY_PRESENT"} in layout["skipped"]


def test_assist_layout_explicit_categories_override(client):
    # a categories override returns a single template (legacy path)
    body = client.post(f"{API}/assist/layout", json=_payload(categories=["sofa", "rug"])).json()
    assert len(_templates(body)) == 1
    cats = [p["category"] for p in _recommended(body)["placements"]]
    assert cats == ["sofa", "rug"] or cats == ["sofa"]  # rug may skip if it can't fit


def test_templates_never_block_the_door(client, catalog_repo):
    """Regression: the multi-template assist must never surface (let alone recommend) a template whose
    TV or sofa collides with the door - overlapping the swing arc OR parked across the door opening.
    Repro: 600x420, door on wall 3, 5 seats, TV requested. The door-colliding 'sofa on the far wall'
    variant is dropped; every surfaced template (and the recommendation) keeps the TV/sofa clear."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.services.spatial.geometry_utils import item_polygon
    from spatial_planning.services.spatial.validate import blocked_door_geom

    room = {
        "vertices": [[0, 0], [600, 0], [600, 420], [0, 420]],
        "doors": [{"id": "d", "wall_index": 3, "offset_cm": 40, "width_cm": 85, "swing": "inward", "hinge": "left"}],
        "windows": [],
    }
    prefs = {
        "seating_capacity": 5,
        "included_pieces": ["rug", "coffee_table", "tv_unit", "floor_lamp", "console", "side_table"],
        "room_type": "living_room",
    }
    body = client.post(f"{API}/assist/layout", json=_payload(room=room, preferences=prefs)).json()
    analysis = analyze_room(Room.model_validate(room))
    templates = _templates(body)
    assert len(templates) >= 1

    def _door_blockers(layout):
        blockers = []
        for p in layout["placements"]:
            if p["category"] not in ("sofa", "tv_unit"):
                continue
            product = catalog_repo.require(p["product_id"])
            poly = item_polygon(p["pose"]["x"], p["pose"]["y"], product.width_cm, product.depth_cm, p["pose"]["rotation_deg"])
            if blocked_door_geom(analysis, product, poly) is not None:
                blockers.append((p["category"], p["pose"]["x"], p["pose"]["y"]))
        return blockers

    # No SURFACED template may have a TV/sofa colliding with the door...
    for t in templates:
        assert _door_blockers(t["layout"]) == [], (t["label"], _door_blockers(t["layout"]))
    # ...and the RECOMMENDED template specifically keeps the TV/sofa clear of the door.
    assert _door_blockers(_recommended(body)) == []


def test_templates_side_table_and_console_never_at_the_door(client, catalog_repo):
    """Regression: the door-clean template gate must cover the SIDE TABLE and CONSOLE/storage, not
    just the sofa/TV. Repro: 480x480, door in the top-right corner (wall 2 offset 0), sofa auto,
    the full checklist opted in (side_table + console). A template with the side table parked flush
    against the door swing must never surface. Every surfaced template keeps all substantial pieces
    (sofa / tv_unit / side_table / console-storage) clear of the swing."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.models.products import placement_group
    from spatial_planning.services.recommend.orchestrator import _TEMPLATE_DOOR_CLEAR_CM
    from spatial_planning.services.spatial.geometry_utils import item_polygon

    room = {
        "vertices": [[0, 0], [480, 0], [480, 480], [0, 480]],
        "doors": [{"id": "d", "wall_index": 2, "offset_cm": 0, "width_cm": 90}],
        "windows": [{"id": "w", "wall_index": 2, "offset_cm": 225, "width_cm": 100}],
    }
    prefs = {
        "seating_capacity": 5,
        "included_pieces": ["rug", "coffee_table", "floor_lamp", "plant", "side_table", "tv_unit", "console", "vases"],
        "room_type": "living_room",
    }
    body = client.post(f"{API}/assist/layout", json=_payload(room=room, preferences=prefs)).json()
    analysis = analyze_room(Room.model_validate(room))
    arcs = list(analysis.swing_arcs.values())
    templates = _templates(body)
    assert len(templates) >= 1

    door_roles = {"sofa", "tv_unit", "side_table", "storage"}
    for t in templates:
        for p in t["layout"]["placements"]:
            if placement_group(p["category"]) not in door_roles:
                continue
            product = catalog_repo.require(p["product_id"])
            poly = item_polygon(p["pose"]["x"], p["pose"]["y"], product.width_cm, product.depth_cm, p["pose"]["rotation_deg"])
            clear = min((poly.distance(a) for a in arcs), default=999.0)
            assert clear >= _TEMPLATE_DOOR_CLEAR_CM, (t["label"], p["category"], clear)


def test_oversized_backstop_exempts_an_explicitly_chosen_sofa(catalog_repo):
    """Regression (Fix 2): the 'oversized piece' template backstop must NOT drop a template whose
    sofa the USER explicitly pinned (sofa_type != 'auto'). The selector honours the explicit choice
    by relaxing the room-proportional width cap, so a legitimate explicit 3-seater can exceed the
    backstop's 1.2x cap; the backstop must exempt it (but still guard the AUTO sofa and every other
    piece)."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.models.preferences import Preferences
    from spatial_planning.models.products import expected_max_width, placement_group
    from spatial_planning.services.recommend.orchestrator import _template_issues, plan_layout_from_recipe

    room = Room(
        vertices=[[0, 0], [480, 0], [480, 480], [0, 480]],
        doors=[{"id": "d", "wall_index": 2, "offset_cm": 0, "width_cm": 90}],
        windows=[{"id": "w", "wall_index": 2, "offset_cm": 225, "width_cm": 100}],
    )
    analysis = analyze_room(room)
    resp = plan_layout_from_recipe(room, Preferences(room_type="living_room"), [], room_type="living_room")
    sofa = next(p for p in resp.placements if p.category == "sofa")
    # Isolate the OVERSIZED backstop: a single sofa, placed clear of the door, no findings - so the
    # only possible drop reason is its size. Then force the sofa clearly OVER the backstop's cap
    # (1.2x the room-proportional max).
    cap = expected_max_width(placement_group(sofa.category), analysis.area_cm2)
    assert cap is not None
    sofa.pose = sofa.pose.model_copy(update={"x": 150.0, "y": 150.0, "rotation_deg": 0.0})
    sofa.product = sofa.product.model_copy(update={"width_cm": cap * 1.5})
    resp.placements = [sofa]
    resp.findings = []

    # AUTO / unpinned: the oversized sofa is (correctly) a drop reason.
    assert _template_issues(resp, analysis, tv_requested=False, sofa_explicit=False) is True
    # Explicitly chosen: the same oversized sofa is EXEMPTED - the template is not dropped for size.
    assert _template_issues(resp, analysis, tv_requested=False, sofa_explicit=True) is False


def test_assist_layout_unknown_room_type_falls_back(client):
    # an unknown room type must fall back, never 500
    body = client.post(f"{API}/assist/layout", json=_payload(room_type="dining")).json()
    assert len(_templates(body)) >= 1
    assert _recommended(body)["totals"]["item_count"] >= 1


# --- Strict door-swing clearance on surfaced templates (extended catalog) --------------------
# The per-item validator tolerates a small (<=5%) swing-arc overlap for autofix leniency; a TEMPLATE
# we RECOMMEND must be cleaner than that. These tests load the LIVE extended catalog (the seat-count
# work there selects a real, sometimes room-oversized sofa) and drive the multi-template planner
# directly, asserting no surfaced sofa/tv overlaps OR hugs a door swing arc.
import pytest  # noqa: E402


@pytest.fixture()
def extended_repo():
    """Point the global catalog at the live extended catalog for a test, then restore the fixture
    catalog so goldens / other tests are unaffected."""
    from spatial_planning.services.catalog import CatalogRepository, set_repository
    from spatial_planning.services.spatial.analyze import clear_cache

    settings = get_settings()
    clear_cache()
    ext = CatalogRepository.load(
        settings.resolve("spatial_planning/data/catalog_extended.json"),
        settings.resolve(settings.static_dir),
    )
    set_repository(ext)
    try:
        yield ext
    finally:
        clear_cache()
        set_repository(
            CatalogRepository.load(settings.resolve("spatial_planning/data/catalog.json"), settings.resolve(settings.static_dir))
        )


def _surfaced_sofa_tv_clearances(resp, arcs):
    """Min distance from each sofa/tv footprint to the NEAREST door swing arc, in cm."""
    from spatial_planning.services.spatial.geometry_utils import item_polygon

    out = []
    for p in resp.placements:
        if p.category in ("sofa", "tv_unit"):
            poly = item_polygon(p.pose.x, p.pose.y, p.product.width_cm, p.product.depth_cm, p.pose.rotation_deg)
            out.append((p.category, min(poly.distance(a) for a in arcs) if arcs else float("inf")))
    return out


def test_assist_templates_drop_doorswing_hugging_variants(extended_repo):
    """Exact repro: 480x360, door wall 0 (offset 40, width 90), window wall 2, 7 seats, 3-seater.
    Template 1 'Sofa under the window' is CLEAN (TV ~20 cm off the swing) and must be recommended;
    Template 2 'Sofa on the right wall' (TV FLUSH at 0 cm) and Template 3 'Sofa on the left wall'
    (sofa OVERLAPS the swing) are both dropped - they pass validate_item's 5% tolerance but must
    never surface. Every surfaced sofa/tv keeps the template swing clearance from every door arc."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.models.preferences import Preferences
    from spatial_planning.services.recommend.orchestrator import (
        _TEMPLATE_DOOR_CLEAR_CM,
        plan_assist_templates,
    )

    room = Room(
        vertices=[[0, 0], [480, 0], [480, 360], [0, 360]],
        doors=[{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
        windows=[{"id": "w", "wall_index": 2, "offset_cm": 150, "width_cm": 120}],
    )
    prefs = Preferences(
        seating_capacity=7,
        sofa_type="3-seater",
        included_pieces=["rug", "coffee_table", "floor_lamp", "plant", "side_table", "tv_unit"],
        style="Mid_Century",
        color_families=["Warm Neutral"],
        room_type="living_room",
    )
    analysis = analyze_room(room)
    arcs = list(analysis.swing_arcs.values())
    assert arcs  # sanity: the door produces a swing arc

    templates = plan_assist_templates(room, prefs, [], room_type="living_room")
    labels = [lbl for lbl, _rec, _resp in templates]

    # the door-colliding right-wall / left-wall variants are dropped...
    assert not any(("right wall" in l) or ("left wall" in l) for l in labels), labels
    # ...leaving the clean under-the-window template, which is the recommendation.
    assert any("under the window" in l for l in labels), labels
    rec_label, rec_flag, _rec_resp = templates[0]
    assert rec_flag is True and "under the window" in rec_label, (rec_label, rec_flag)

    # every surfaced sofa/tv keeps the swing clearance from EVERY door arc (no overlap, no hug)
    for lbl, _rec, resp in templates:
        for cat, clr in _surfaced_sofa_tv_clearances(resp, arcs):
            assert clr >= _TEMPLATE_DOOR_CLEAR_CM, (lbl, cat, clr)


def test_assist_templates_door_sweep_no_swing_collision(extended_repo):
    """Broad door sweep: across room shapes x door walls x seat counts (incl. 7 with a 3-seater),
    NO surfaced/recommended template may have a sofa or TV overlapping or hugging any door swing arc
    (within the template clearance). Guards the fix against a variant leaking through on any wall."""
    from spatial_planning.models.geometry import Room
    from spatial_planning.models.preferences import Preferences
    from spatial_planning.services.recommend.orchestrator import (
        _TEMPLATE_DOOR_CLEAR_CM,
        plan_assist_templates,
    )

    room_shapes = [
        [[0, 0], [480, 0], [480, 360], [0, 360]],
        [[0, 0], [600, 0], [600, 420], [0, 420]],
        [[0, 0], [420, 0], [420, 480], [0, 480]],
    ]
    seat_specs = [(3, "auto"), (5, "3-seater"), (7, "3-seater")]
    configs = 0
    violations = []
    for verts in room_shapes:
        for door_wall in range(4):
            window_wall = 2 if door_wall != 2 else 0  # a window on some OTHER wall
            room = Room(
                vertices=verts,
                doors=[{"id": "d", "wall_index": door_wall, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
                windows=[{"id": "w", "wall_index": window_wall, "offset_cm": 120, "width_cm": 120}],
            )
            analysis = analyze_room(room)
            arcs = list(analysis.swing_arcs.values())
            for seats, sofa_type in seat_specs:
                configs += 1
                prefs = Preferences(
                    seating_capacity=seats,
                    sofa_type=sofa_type,
                    included_pieces=["rug", "coffee_table", "tv_unit", "side_table"],
                    room_type="living_room",
                )
                templates = plan_assist_templates(room, prefs, [], room_type="living_room")
                for lbl, _rec, resp in templates:
                    for cat, clr in _surfaced_sofa_tv_clearances(resp, arcs):
                        if clr < _TEMPLATE_DOOR_CLEAR_CM:
                            violations.append((verts[1][0], verts[2][1], door_wall, seats, sofa_type, lbl, cat, round(clr, 1)))

    assert configs == len(room_shapes) * 4 * len(seat_specs)  # 3 x 4 x 3 = 36 configs swept
    assert violations == [], violations
