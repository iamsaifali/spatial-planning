"""Render endpoint guards that sit in front of any OpenAI call."""

import base64

API = "/api/v1"
ROOM = {"vertices": [[0, 0], [480, 0], [480, 360], [0, 360]]}


def test_render_disabled_without_key(client):
    r = client.post(f"{API}/render", json={"room": ROOM, "placed_items": [], "canvas_png_b64": "aGVsbG8="})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "RENDER_DISABLED"


def test_render_oversize_png_413(keyed_client):
    big = base64.b64encode(b"x" * (5 * 1024 * 1024)).decode()
    r = keyed_client.post(f"{API}/render", json={"room": ROOM, "placed_items": [], "canvas_png_b64": big})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PNG_TOO_LARGE"


def test_render_bad_base64_422(keyed_client):
    r = keyed_client.post(
        f"{API}/render", json={"room": ROOM, "placed_items": [], "canvas_png_b64": "!!!not-base64!!!"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "RENDER_FAILED"


def test_health_reports_render_enabled_with_key(keyed_client):
    body = keyed_client.get(f"{API}/health").json()
    assert body["llm_enabled"] is True and body["render_enabled"] is True
