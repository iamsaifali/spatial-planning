"""SAR/USD currency support: /config, conversion, validation."""

API = "/api/v1"
ROOM = {"vertices": [[0, 0], [480, 0], [480, 360], [0, 360]]}
CONTACT = {"name": "Sara", "email": "sara@example.com"}


def test_config_exposes_currency_setup(client):
    r = client.get(f"{API}/config")
    assert r.status_code == 200
    cur = r.json()["currency"]
    assert cur["supported"] == ["USD", "SAR"]
    assert cur["base"] == "USD"
    assert cur["default"] == "SAR"
    assert cur["rates"]["USD"] == 1.0
    assert cur["rates"]["SAR"] == 3.75
    assert r.json()["scene"]["wall_thickness_cm"] == 12


def test_opening_height_validation(client):
    tall_door = {
        "vertices": [[0, 0], [400, 0], [400, 300], [0, 300]],
        "wall_height_cm": 240,
        "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 50, "width_cm": 90, "height_cm": 250}],
    }
    r = client.post(f"{API}/rooms/validate", json={"room": tall_door})
    assert r.json()["valid"] is False
    assert any(i["code"] == "OPENING_INVALID" for i in r.json()["issues"])

    tall_window = {
        "vertices": [[0, 0], [400, 0], [400, 300], [0, 300]],
        "wall_height_cm": 240,
        "windows": [{"id": "w1", "wall_index": 0, "offset_cm": 50, "width_cm": 120,
                     "sill_height_cm": 150, "height_cm": 120}],
    }
    r = client.post(f"{API}/rooms/validate", json={"room": tall_window})
    assert r.json()["valid"] is False


def test_checkout_records_sar_display_total(client):
    r = client.post(
        f"{API}/checkout",
        json={"items": [{"product_id": "sofa-001", "qty": 1}], "contact": CONTACT, "currency": "SAR"},
    )
    assert r.status_code == 200
    order = r.json()
    assert order["currency"] == "SAR"
    assert order["display_total"] == round(order["total"] * 3.75)

    fetched = client.get(f"{API}/orders/{order['order_id']}").json()
    assert fetched["currency"] == "SAR"
    assert fetched["display_total"] == order["display_total"]


def test_checkout_usd_and_default(client):
    r = client.post(
        f"{API}/checkout",
        json={"items": [{"product_id": "rug-001", "qty": 2}], "contact": CONTACT, "currency": "usd"},
    )
    assert r.status_code == 200
    assert r.json()["currency"] == "USD"
    assert r.json()["display_total"] == r.json()["total"]

    # no currency -> DEFAULT_CURRENCY (SAR)
    r = client.post(
        f"{API}/checkout",
        json={"items": [{"product_id": "rug-001", "qty": 1}], "contact": CONTACT},
    )
    assert r.json()["currency"] == "SAR"


def test_unsupported_currency_rejected(client):
    r = client.post(
        f"{API}/checkout",
        json={"items": [{"product_id": "rug-001", "qty": 1}], "contact": CONTACT, "currency": "EUR"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_CURRENCY"

    r = client.post(f"{API}/summary", json={"room": ROOM, "placed_items": [], "currency": "INR"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_CURRENCY"


def test_summary_accepts_currency(client):
    r = client.post(f"{API}/summary", json={"room": ROOM, "placed_items": [], "currency": "SAR"})
    assert r.status_code == 200
