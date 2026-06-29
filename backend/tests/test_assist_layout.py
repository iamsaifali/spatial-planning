"""POST /assist/layout - deterministic whole-room auto-planner (now returns templates)."""

from app.models.geometry import PlacedItem
from app.models.validation import MUST_FIX_CODES
from app.services.spatial.analyze import analyze_room
from app.services.spatial.validate import validate_item

API = "/api/v1"

ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 180, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 150, "width_cm": 160}],
}
PREFS = {"styles": ["modern"], "budget_tier": "mid", "total_budget": 8000, "room_purpose": "entertaining"}


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
    # a normal living room offers a few position templates, each a distinct valid layout
    body = client.post(f"{API}/assist/layout", json=_payload()).json()
    templates = _templates(body)
    assert len(templates) >= 2
    ids = [t["layout"]["proposal_id"] for t in templates]
    assert len(set(ids)) == len(ids)  # genuinely different arrangements
    assert len({t["label"] for t in templates}) == len(templates)  # unique names
    for t in templates:  # every option is gate-valid
        assert not [f for f in t["layout"]["findings"] if f["severity"] == "error"]


def test_assist_layout_placements_have_no_hard_errors(client, catalog_repo):
    from app.models.geometry import Room

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


def test_assist_layout_unknown_room_type_falls_back(client):
    # an unknown room type must fall back, never 500
    body = client.post(f"{API}/assist/layout", json=_payload(room_type="dining")).json()
    assert len(_templates(body)) >= 1
    assert _recommended(body)["totals"]["item_count"] >= 1
