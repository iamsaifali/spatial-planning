"""P3: generate a complete, shoppable majlis (real products) + capacity, via service+API."""

from app.models.geometry import Room
from app.models.preferences import Preferences
from app.services.majlis.generate import generate_majlis
from app.services.spatial.analyze import analyze_room
from app.services.spatial.geometry_utils import item_polygon

API = "/api/v1"
ROOM = {
    "vertices": [[0, 0], [760, 0], [760, 640], [0, 640]],
    "doors": [{"id": "d1", "wall_index": 1, "offset_cm": 150, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 0, "offset_cm": 120, "width_cm": 220, "sill_height_cm": 95}],
}


def _room() -> Room:
    return Room(**{**ROOM, "wall_height_cm": 270})


def test_generate_tiles_one_sofa_with_accessories(catalog_repo):
    res = generate_majlis(_room(), Preferences(room_type="majlis", styles=["modern"]))
    sofas = [i for i in res.placed_items if i.instance_id.startswith("majlis-sofa-")]
    assert res.seats > 0 and len(sofas) >= 4  # at least one per wall
    assert len({i.product_id for i in sofas}) == 1, "majlis seating should be one uniform sofa model"
    cats = {i.instance_id.split("-")[1] for i in res.placed_items}
    assert "rug" in cats, "expected a central rug"


def test_generated_layout_is_geometrically_clean(catalog_repo):
    res = generate_majlis(_room(), Preferences(room_type="majlis"))
    analysis = analyze_room(_room())
    room_buffered = analysis.polygon.buffer(1.5)
    polys, walkable = [], []
    for it in res.placed_items:
        prod = catalog_repo.require(it.product_id)
        polys.append(item_polygon(it.x, it.y, prod.width_cm, prod.depth_cm, it.rotation_deg))
        walkable.append(prod.category == "rug")
    # in bounds
    for poly in polys:
        assert poly.difference(room_buffered).area <= 0.01 * poly.area
    # no overlap between non-walkable items
    solid = [p for p, w in zip(polys, walkable) if not w]
    for a in range(len(solid)):
        for b in range(a + 1, len(solid)):
            inter = solid[a].intersection(solid[b])
            assert inter.is_empty or inter.area <= 0.02 * min(solid[a].area, solid[b].area)
    # nothing blocks a door swing
    for poly in solid:
        for arc in analysis.swing_arcs.values():
            assert poly.intersection(arc).area <= 0.05 * arc.area


def test_generate_endpoint(client):
    r = client.post(f"{API}/majlis/generate", json={"room": ROOM, "preferences": {"room_type": "majlis"}})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["seats"] > 0
    assert len(data["placed_items"]) >= 4
    assert "majlis" in data["note"].lower()


def test_generate_tiny_room_is_honest(catalog_repo):
    res = generate_majlis(
        Room(vertices=[[0, 0], [300, 0], [300, 260], [0, 260]], doors=[], windows=[], wall_height_cm=270),
        Preferences(room_type="majlis"),
    )
    # too small for a majlis -> no seating, honest note, no crash
    assert res.seats == 0
    assert "too small" in res.note.lower()
