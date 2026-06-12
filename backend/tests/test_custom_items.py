"""User-kept ('existing') items: occupy space, cost nothing, never recommended."""

API = "/api/v1"

ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90}],
}

CUSTOM = {
    "instance_id": "mine-1",
    "product_id": "custom-1",
    "x": 240,
    "y": 180,
    "rotation_deg": 0,
    "custom": {"name": "Grandma's cabinet", "width_cm": 120, "depth_cm": 45, "height_cm": 160},
}


def test_custom_item_flows(client):
    # validate: a second item overlapping the custom one is flagged
    overlapping = {
        "instance_id": "s1", "product_id": "sofa-001",
        "x": 240, "y": 180, "rotation_deg": 0,
    }
    r = client.post(
        f"{API}/placement/validate",
        json={"room": ROOM, "placed_items": [CUSTOM], "item": overlapping},
    )
    assert r.status_code == 200
    assert any(f["code"] == "OVERLAP_ITEM" for f in r.json()["findings"])

    # summary: custom item appears as a zero-price line and counts no category weight
    r = client.post(f"{API}/summary", json={"room": ROOM, "placed_items": [CUSTOM]})
    assert r.status_code == 200
    body = r.json()
    assert body["total_price"] == 0
    assert body["items"][0]["product"]["category"] == "custom"
    assert body["items"][0]["product"]["name"] == "Grandma's cabinet"
    assert body["completeness_pct"] == 0

    # guide step works with a custom item present (zones avoid it)
    r = client.post(f"{API}/guide/step/sofa", json={"room": ROOM, "placed_items": [CUSTOM]})
    assert r.status_code == 200
    assert all(rec["product"]["category"] == "sofa" for rec in r.json()["recommendations"])

    # designs round-trip preserves the custom spec
    r = client.post(f"{API}/designs", json={"room": ROOM, "placed_items": [CUSTOM]})
    assert r.status_code == 200
    design_id = r.json()["design_id"]
    r = client.get(f"{API}/designs/{design_id}")
    assert r.json()["placed_items"][0]["custom"]["name"] == "Grandma's cabinet"


def test_validating_the_custom_item_itself(client):
    # the candidate item (not just placed_items) may be a kept item
    r = client.post(
        f"{API}/placement/validate",
        json={"room": ROOM, "placed_items": [], "item": CUSTOM},
    )
    assert r.status_code == 200
    # centred 120cm cabinet in a 4.8x3.6 room: no error-level findings
    assert not [f for f in r.json()["findings"] if f["severity"] == "error"]


def test_custom_item_requires_spec(client):
    # product_id not in catalog and no custom spec -> UNKNOWN_PRODUCT
    bogus = {**CUSTOM, "custom": None}
    r = client.post(f"{API}/summary", json={"room": ROOM, "placed_items": [bogus]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_PRODUCT"


def test_mrp_present_and_valid(client):
    r = client.get(f"{API}/products", params={"page_size": 100})
    items = r.json()["items"]
    with_mrp = [p for p in items if p.get("mrp")]
    assert len(with_mrp) >= 30
    assert all(p["mrp"] > p["price"] for p in with_mrp)
