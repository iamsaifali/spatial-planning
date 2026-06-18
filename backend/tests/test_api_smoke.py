"""End-to-end happy path + key error paths through the HTTP layer (no OpenAI key)."""

API = "/api/v1"

ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
}


def test_full_happy_path(client):
    # health
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["llm_enabled"] is False

    # validate + analyze
    r = client.post(f"{API}/rooms/validate", json={"room": ROOM})
    assert r.status_code == 200 and r.json()["valid"] is True
    r = client.post(f"{API}/rooms/analyze", json={"room": ROOM})
    assert r.status_code == 200
    analysis = r.json()
    assert analysis["zones"] and analysis["walls"] and analysis["analysis_hash"]

    # guide steps
    r = client.post(f"{API}/guide/steps", json={"room": ROOM, "placed_items": []})
    assert r.status_code == 200 and len(r.json()["steps"]) == 9

    # sofa step with recommendations
    r = client.post(f"{API}/guide/step/sofa", json={"room": ROOM, "placed_items": []})
    assert r.status_code == 200
    step = r.json()
    assert step["guidance"]["message"]
    assert step["guidance"]["copy_source"] == "template"
    assert len(step["recommendations"]) == 3
    best = step["recommendations"][0]
    assert best["why_it_fits"]["why_product"]
    pose = best["suggested_pose"]

    placed = [{
        "instance_id": "s1",
        "product_id": best["product"]["id"],
        "x": pose["x"], "y": pose["y"], "rotation_deg": pose["rotation_deg"],
    }]

    # validate the suggested pose - should be free of errors
    r = client.post(
        f"{API}/placement/validate",
        json={"room": ROOM, "placed_items": [], "item": placed[0]},
    )
    assert r.status_code == 200
    assert not [f for f in r.json()["findings"] if f["severity"] == "error"]

    # a clearly bad pose gets findings + a fix
    bad = {"instance_id": "s2", "product_id": best["product"]["id"], "x": 470, "y": 180, "rotation_deg": 0}
    r = client.post(f"{API}/placement/validate", json={"room": ROOM, "placed_items": placed, "item": bad})
    assert r.status_code == 200
    body = r.json()
    assert body["findings"]
    assert body["autofix"] is not None or body["better_placement"] is not None

    # placement suggest for a rug after the sofa
    r = client.post(
        f"{API}/placement/suggest",
        json={"room": ROOM, "placed_items": placed, "product_id": "rug-001"},
    )
    assert r.status_code == 200 and "pose" in r.json()

    # summary
    r = client.post(f"{API}/summary", json={"room": ROOM, "placed_items": placed})
    assert r.status_code == 200
    summary = r.json()
    assert summary["total_price"] == best["product"]["price"]
    # completeness is now plan-relative: one sofa of a multi-item plan -> partial
    assert 0 < summary["completeness_pct"] < 100
    assert summary["narrative"]["text"]
    assert any(m["category"] == "rug" for m in summary["missing_essentials"])

    # designs round trip
    r = client.post(f"{API}/designs", json={"room": ROOM, "placed_items": placed, "name": "Test Room"})
    assert r.status_code == 200
    design_id = r.json()["design_id"]
    r = client.get(f"{API}/designs/{design_id}")
    assert r.status_code == 200
    assert r.json()["placed_items"][0]["product_id"] == placed[0]["product_id"]
    r = client.get(f"{API}/designs")
    assert any(d["design_id"] == design_id for d in r.json()["items"])

    # checkout
    r = client.post(
        f"{API}/checkout",
        json={
            "items": [{"product_id": placed[0]["product_id"], "qty": 1}],
            "contact": {"name": "Asha", "email": "asha@example.com"},
        },
    )
    assert r.status_code == 200
    order = r.json()
    assert order["status"] == "mock_confirmed" and order["total"] > 0
    r = client.get(f"{API}/orders/{order['order_id']}")
    assert r.status_code == 200

    # render disabled without key
    r = client.post(
        f"{API}/render",
        json={"room": ROOM, "placed_items": placed, "canvas_png_b64": "aGVsbG8="},
    )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "RENDER_DISABLED"

    # assistant offline mode
    r = client.post(
        f"{API}/assistant/ask",
        json={"question": "Where should my sofa go?", "room": ROOM, "placed_items": placed},
    )
    assert r.status_code == 200
    assert r.json()["copy_source"] == "offline" and r.json()["answer"]

    # products
    r = client.get(f"{API}/products", params={"category": "sofa"})
    assert r.status_code == 200 and r.json()["total"] == 16
    r = client.get(f"{API}/products/sofa-001")
    assert r.status_code == 200 and r.json()["image_url"].startswith("/static/products/")


def test_error_paths(client):
    # invalid room
    bowtie = {"vertices": [[0, 0], [400, 300], [400, 0], [0, 300]]}
    r = client.post(f"{API}/rooms/analyze", json={"room": bowtie})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ROOM_INVALID"

    # unknown product in placed items
    r = client.post(
        f"{API}/guide/step/sofa",
        json={"room": ROOM, "placed_items": [{"instance_id": "x", "product_id": "nope", "x": 0, "y": 0}]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_PRODUCT"

    # duplicate instance ids
    dup = {"instance_id": "x", "product_id": "sofa-001", "x": 0, "y": 0}
    r = client.post(f"{API}/summary", json={"room": ROOM, "placed_items": [dup, dup]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "DUPLICATE_INSTANCE"

    # unknown step + design + product 404s
    assert client.post(f"{API}/guide/step/bathtub", json={"room": ROOM}).status_code == 404
    assert client.get(f"{API}/designs/zzzzzzzzzz").status_code == 404
    assert client.get(f"{API}/products/nope").status_code == 404

    # malformed payload -> envelope
    r = client.post(f"{API}/rooms/analyze", json={"room": {"vertices": "oops"}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    # empty checkout
    r = client.post(f"{API}/checkout", json={"contact": {"name": "A", "email": "a@b.co"}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "EMPTY_CART"
