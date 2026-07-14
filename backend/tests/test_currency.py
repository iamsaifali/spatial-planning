"""SAR/USD currency support exposed via /config."""

API = "/api/v1"


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
