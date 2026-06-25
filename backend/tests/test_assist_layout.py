"""POST /assist/layout - deterministic whole-room auto-planner."""

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


def test_assist_layout_full_room(client):
    r = client.post(f"{API}/assist/layout", json=_payload())
    assert r.status_code == 200
    body = r.json()

    assert body["proposal_id"].startswith("lay_")
    assert len(body["placements"]) >= 3  # criterion: multiple valid placements
    assert body["totals"]["item_count"] == len(body["placements"])
    assert body["totals"]["currency"] == "USD"

    # every placement carries a full product + a deterministic (non-LLM) rationale
    first = body["placements"][0]
    assert first["category"] == "sofa"  # living-room sequence starts with the sofa
    assert first["product"]["id"] == first["product_id"]
    assert first["rationale"]
    assert body["skipped"] == [] or all("reason" in s for s in body["skipped"])


def test_assist_layout_placements_have_no_hard_errors(client, catalog_repo):
    from app.models.geometry import Room

    r = client.post(f"{API}/assist/layout", json=_payload())
    body = r.json()
    room = Room.model_validate(ROOM)
    analysis = analyze_room(room)

    placed: list[tuple[PlacedItem, object]] = []
    for p in body["placements"]:
        item = PlacedItem(
            instance_id=p["instance_id"],
            product_id=p["product_id"],
            x=p["pose"]["x"],
            y=p["pose"]["y"],
            rotation_deg=p["pose"]["rotation_deg"],
        )
        product = catalog_repo.require(p["product_id"])
        findings = validate_item(analysis, placed, item, product)
        assert not [f for f in findings if f.code in MUST_FIX_CODES], (p["category"], findings)
        placed.append((item, product))


def test_assist_layout_is_deterministic(client):
    a = client.post(f"{API}/assist/layout", json=_payload()).json()
    b = client.post(f"{API}/assist/layout", json=_payload()).json()
    assert a["proposal_id"] == b["proposal_id"]


def test_assist_layout_respects_existing_items(client):
    # user already placed a sofa - the planner must not add a second one
    sofa = {"instance_id": "mine", "product_id": "sofa-001", "x": 240, "y": 305, "rotation_deg": 180}
    r = client.post(f"{API}/assist/layout", json=_payload(placed_items=[sofa]))
    body = r.json()
    assert "sofa" not in [p["category"] for p in body["placements"]]
    assert {"category": "sofa", "reason": "ALREADY_PRESENT"} in body["skipped"]


def test_assist_layout_explicit_categories_override(client):
    r = client.post(f"{API}/assist/layout", json=_payload(categories=["sofa", "rug"]))
    cats = [p["category"] for p in r.json()["placements"]]
    assert cats == ["sofa", "rug"] or cats == ["sofa"]  # rug may skip if it can't fit


def test_assist_layout_unknown_room_type_falls_back(client):
    # "majlis" is reserved but not implemented yet - must fall back, never 500
    r = client.post(f"{API}/assist/layout", json=_payload(room_type="majlis"))
    assert r.status_code == 200
    assert r.json()["totals"]["item_count"] >= 1
