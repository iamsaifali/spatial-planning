"""Majlis zone generation for the GUIDED flow.

Unlike the batch generator, this feeds the existing family step/recommend engine: each
category step returns the SINGLE next target spot, so the user gets product recommendations
for that spot and places one at a time (sofa -> next open wall slot; rug -> centre;
side table/lighting/decor -> next open corner). Reuses the family ZoneData + anchor_pose +
selector. Reads the shared RoomAnalysis; mutates nothing.
"""

from shapely.geometry import Polygon

from app.models.geometry import PlacedItem, Pose
from app.models.products import Product
from app.services.spatial.core import RoomAnalysis, ZoneData
from app.services.spatial.geometry_utils import (
    add,
    dist,
    dot,
    item_polygon,
    quad,
    rotation_for_normal,
    sub,
    unit,
)

PlacedProduct = tuple[PlacedItem, Product]

R_PERIMETER = "perimeter_seating"
R_OPEN_CENTRE = "anchors_open_centre"
R_CORNER = "fills_open_corner"
SEAT_GAP = 14.0
WALL_END_EPS = 1.0


def _subtract(a: float, b: float, blocks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[a,b] minus the blocked sub-intervals -> the clear sub-intervals."""
    clear = [(a, b)]
    for lo, hi in blocks:
        nxt: list[tuple[float, float]] = []
        for ca, cb in clear:
            if hi <= ca or lo >= cb:
                nxt.append((ca, cb))
                continue
            if lo > ca:
                nxt.append((ca, lo))
            if hi < cb:
                nxt.append((hi, cb))
        clear = nxt
    return clear


def _sofa_span_on_wall(item: PlacedItem, product: Product, wall) -> tuple[float, float] | None:
    """If a placed sofa sits against this wall, its [lo,hi] extent along the wall axis."""
    c = (item.x, item.y)
    perp = dot(sub(c, wall.start), wall.normal)  # distance off the wall into the room
    if not (-2.0 <= perp <= product.depth_cm + 40.0):
        return None
    if dot((item.x - wall.start[0], item.y - wall.start[1]), wall.normal) < -5.0:
        return None
    poly = item_polygon(item.x, item.y, product.width_cm, product.depth_cm, item.rotation_deg)
    xs = [dot(sub(p, wall.start), wall.dir) for p in poly.exterior.coords]
    return (min(xs), max(xs))


def _corner_reserve(analysis: RoomAnalysis, wall, depth: float) -> tuple[float, float]:
    """Reserve only each wall's START corner (the END corner is owned by the next wall), so
    every corner is reserved exactly once - preventing perpendicular collisions - while
    filling all walls evenly (long walls keep both ends usable except their own start)."""
    return depth + 10.0, SEAT_GAP


class _RepSofa:
    """Stand-in product for the slot-viability filter (anchor_pose only reads w/d/category)."""

    category = "sofa"
    id = "__rep_sofa__"

    def __init__(self, width_cm: float, depth_cm: float) -> None:
        self.width_cm = width_cm
        self.depth_cm = depth_cm


def _sofa_pose_ok(analysis: RoomAnalysis, placed, product, pose: Pose) -> bool:
    """A majlis sofa pose is acceptable only if it stays inside the room, clear of every door
    swing / keep-clear band, and off any already-placed sofa. (No rotation tolerance: a majlis
    sofa must sit flush to its wall.)"""
    poly = item_polygon(pose.x, pose.y, product.width_cm, product.depth_cm, pose.rotation_deg)
    if poly.difference(analysis.polygon.buffer(1.5)).area > 0.02 * poly.area:
        return False
    kc = analysis.keep_clear_union
    if not kc.is_empty and poly.intersection(kc).area > 0.03 * poly.area:
        return False
    for it, p in placed:
        op = item_polygon(it.x, it.y, p.width_cm, p.depth_cm, it.rotation_deg)
        if poly.intersection(op).area > 0.05 * min(poly.area, op.area):
            return False
    return True


def _sofa_pose_in_zone(analysis: RoomAnalysis, placed_sofas, product, zone: ZoneData) -> Pose | None:
    """A flush, wall-aligned pose for `product` in a sofa wall-slot, slid ALONG the wall to clear
    a door / keep-clear band. Returns None if it can't sit flush & clear (caller then tries the
    next wall) - never rotates the sofa off the wall the way the family `settle_pose` would."""
    from app.services.spatial.zones import anchor_pose

    base = anchor_pose(zone, product, analysis)
    if zone.wall_index is None or zone.seg is None:
        return base if _sofa_pose_ok(analysis, placed_sofas, product, base) else None
    wall = analysis.walls[zone.wall_index]
    a, b = zone.seg
    slack = max(0.0, (b - a) - product.width_cm - 4.0)  # room to slide from the slot start
    dx, dy = wall.dir
    for frac in (0.0, 1.0, 0.5, 0.25, 0.75):
        d = slack * frac
        cand = Pose(x=round(base.x + dx * d, 1), y=round(base.y + dy * d, 1), rotation_deg=base.rotation_deg)
        if _sofa_pose_ok(analysis, placed_sofas, product, cand):
            return cand
    return None


def majlis_sofa_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats) -> list[ZoneData]:
    """Open perimeter slots, RANKED (fills wall 0 first, then 1, 2, 3), with any slot that a
    sofa can't occupy flush & clear of a door swing dropped - so placement skips a door-blocked
    run instead of mangling a sofa into it. The caller takes the first slot the real product fits."""
    s = stats.get("sofa", {})
    depth = s.get("max_d", 102.0) + 8.0
    min_w = s.get("min_w", 152.0)
    placed_sofas = [(i, p) for i, p in placed if p.category == "sofa"]

    cands: list[tuple[tuple[float, float], ZoneData]] = []
    for wall in analysis.walls:
        cr_start, cr_end = _corner_reserve(analysis, wall, depth)
        spans = []
        for i, p in placed_sofas:
            span = _sofa_span_on_wall(i, p, wall)
            if span is not None:
                spans.append((span[0] - SEAT_GAP, span[1] + SEAT_GAP))
        for a, b in wall.clear_floor:
            lo = a + (cr_start if a <= WALL_END_EPS else SEAT_GAP)
            hi = b - (cr_end if b >= wall.length - WALL_END_EPS else SEAT_GAP)
            for rlo, rhi in _subtract(lo, hi, spans):
                if rhi - rlo < min_w:
                    continue
                # priority: earlier wall first, then earlier position along the wall
                key = (float(len(analysis.walls) - wall.index), -rlo)
                cands.append((key, _band_zone(analysis, wall, rlo, rhi, depth)))
    cands.sort(key=lambda kz: kz[0], reverse=True)

    rep = _RepSofa(REP_SOFA_WIDTH, s.get("max_d", 102.0))
    return [z for _k, z in cands if _sofa_pose_in_zone(analysis, placed_sofas, rep, z) is not None]


REP_SOFA_WIDTH = 206.0  # representative sofa width for the up-front slot/seat estimate
SEATS_PER_SOFA = 3


def count_sofa_slots(analysis: RoomAnalysis, stats, width: float | None = None) -> int:
    """How many perimeter sofa slots the room holds (matches the guided packing), for the
    plan's seat estimate. `width` overrides the representative sofa width - pass the catalogue's
    narrowest sofa for the high end of the range, the widest for the low end."""
    s = stats.get("sofa", {})
    depth = s.get("max_d", 102.0) + 8.0
    width = REP_SOFA_WIDTH if width is None else width
    total = 0
    for wall in analysis.walls:
        cr_start, cr_end = _corner_reserve(analysis, wall, depth)
        for a, b in wall.clear_floor:
            lo = a + (cr_start if a <= WALL_END_EPS else SEAT_GAP)
            hi = b - (cr_end if b >= wall.length - WALL_END_EPS else SEAT_GAP)
            run = hi - lo
            if run >= width:
                total += int((run + SEAT_GAP) // (width + SEAT_GAP))
    return total


def _band_zone(analysis: RoomAnalysis, wall, rlo: float, rhi: float, depth: float) -> ZoneData:
    band = quad(
        add(wall.point_at(rlo), wall.normal, 2.0),
        add(wall.point_at(rhi), wall.normal, 2.0),
        add(wall.point_at(rhi), wall.normal, 2.0 + depth),
        add(wall.point_at(rlo), wall.normal, 2.0 + depth),
    ).intersection(analysis.polygon)
    if isinstance(band, Polygon) and band.is_empty:
        band = analysis.polygon
    return ZoneData(
        id=f"z-majlis-sofa-w{wall.index}",
        category="sofa",
        polygon=band if isinstance(band, Polygon) else analysis.polygon,
        score=0.95,
        rotation_deg=rotation_for_normal(wall.normal),
        anchor_label=f"wall_{wall.index}",
        reason_codes=[R_PERIMETER],
        kind="wall_band",
        wall_index=wall.index,
        seg=(rlo, rhi),
        band_depth=depth,
        anchor_t=0.0,  # pack from the open-run start (next to the corner / previous sofa)
    )


def majlis_rug_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats) -> list[ZoneData]:
    """One central rug spot in the open middle."""
    minx, miny, maxx, maxy = analysis.polygon.bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    lat = min(0.55 * (maxx - minx), 380.0)
    fwd = min(0.55 * (maxy - miny), 300.0)
    rect = item_polygon(cx, cy, lat, fwd, 0.0).intersection(analysis.polygon)
    return [
        ZoneData(
            id="z-majlis-rug",
            category="rug",
            polygon=rect if isinstance(rect, Polygon) and not rect.is_empty else analysis.polygon,
            score=0.9,
            rotation_deg=0.0,
            anchor_label="open_centre",
            reason_codes=[R_OPEN_CENTRE],
            kind="free",
            origin=(cx, cy),
            fwd=(0.0, 1.0),
            lat=(1.0, 0.0),
            fwd_len=fwd,
            lat_len=lat,
            place_at_origin=True,
        )
    ]


ACCESSORY_CATS = ("side_table", "lighting", "decor")
# candidate footprint (cm) used to reserve clear space per accessory type
_CORNER_SIZE = {"side_table": 55.0, "lighting": 55.0, "decor": 60.0}
# which kind of spot each accessory prefers; the other kind is still allowed as fallback
_PREFERS = {"side_table": "sofa_end", "lighting": "corner", "decor": "corner"}
_PREFER_BONUS = 1000.0  # added to a spot's spread score when it matches the category preference


def _sofa_wall(analysis: RoomAnalysis, item: PlacedItem, product: Product):
    """The wall a placed sofa backs onto, plus its [lo,hi] span along that wall axis.
    Returns (wall, lo, hi) or None. Picks the wall with the smallest perpendicular gap."""
    best = None
    best_perp = 1e9
    for wall in analysis.walls:
        perp = dot(sub((item.x, item.y), wall.start), wall.normal)
        if perp < -2.0 or perp > product.depth_cm + 30.0:
            continue
        span = _sofa_span_on_wall(item, product, wall)
        if span is None:
            continue
        if perp < best_perp:
            best_perp = perp
            best = (wall, span[0], span[1])
    return best


def _sofa_end_spots(
    analysis: RoomAnalysis, placed: list[PlacedProduct], size: float
) -> list[tuple[tuple[float, float], float, str]]:
    """Against-the-wall spots flush at each sofa's end (arm's reach of the end seat).
    Returns (centre, rotation, kind='sofa_end')."""
    out = []
    for i, p in placed:
        if p.category != "sofa":
            continue
        sw = _sofa_wall(analysis, i, p)
        if sw is None:
            continue
        wall, lo, hi = sw
        for t_center in (hi + SEAT_GAP + size / 2.0, lo - SEAT_GAP - size / 2.0):
            if t_center - size / 2.0 < 1.0 or t_center + size / 2.0 > wall.length - 1.0:
                continue
            c = add(wall.point_at(t_center), wall.normal, size / 2.0 + 2.0)
            out.append((c, rotation_for_normal(wall.normal), "sofa_end"))
    return out


def _corner_spots(
    analysis: RoomAnalysis, size: float
) -> list[tuple[tuple[float, float], float, str]]:
    """Diagonal spots tucked into each room corner. Returns (centre, rotation=0, kind='corner')."""
    verts = analysis.room.vertices
    n = len(verts)
    out = []
    for idx in range(n):
        prev_w = analysis.walls[(idx - 1) % n]
        next_w = analysis.walls[idx % n]
        diag = unit(prev_w.normal[0] + next_w.normal[0], prev_w.normal[1] + next_w.normal[1])
        if diag != (0.0, 0.0):
            out.append((add(verts[idx], diag, size / 2.0 + 14.0), 0.0, "corner"))
    return out


def majlis_accessory_zones(
    analysis: RoomAnalysis, placed: list[PlacedProduct], category: str, size: float
) -> list[ZoneData]:
    """Place one accessory at the clear perimeter spot that's MOST spread from the others.

    Pools two spot kinds - sofa-ends (flush to the wall beside a seat) and room corners - then
    picks the clear one maximising distance to every already-placed accessory, biased toward the
    category's preferred kind (side tables -> sofa-ends; lamps/plants -> corners). This keeps
    side tables within arm's reach of a sofa and stops everything stacking in one corner, while
    still finding a home in tight, fully-seated rooms where one kind of spot is exhausted."""
    others = [(it.x, it.y) for it, p in placed if p.category in ACCESSORY_CATS]
    prefer = _PREFERS.get(category, "corner")

    candidates = _sofa_end_spots(analysis, placed, size) + _corner_spots(analysis, size)
    best = None
    best_key = -1e18
    for (cx, cy), rot, kind in candidates:
        poly = item_polygon(cx, cy, size, size, rot)
        if not _accessory_clear(analysis, poly, placed):
            continue
        spread = min((dist((cx, cy), o) for o in others), default=1e6)
        key = spread + (_PREFER_BONUS if kind == prefer else 0.0)
        if key > best_key:
            best_key = key
            best = (cx, cy, rot, kind)
    if best is None:
        return []

    cx, cy, rot, kind = best
    rect = item_polygon(cx, cy, size, size, rot).intersection(analysis.polygon)
    return [
        ZoneData(
            id=f"z-majlis-{category}-{kind}",
            category=category,
            polygon=rect if isinstance(rect, Polygon) and not rect.is_empty else analysis.polygon,
            score=0.85 if kind == prefer else 0.8,
            rotation_deg=rot,
            anchor_label="beside_sofa" if kind == "sofa_end" else "corner",
            reason_codes=[R_CORNER],
            kind="free",
            origin=(cx, cy),
            fwd=(0.0, 1.0),
            lat=(1.0, 0.0),
            fwd_len=size,
            lat_len=size,
            place_at_origin=True,
        )
    ]


def majlis_coffee_table_zones(analysis: RoomAnalysis, placed: list[PlacedProduct], stats) -> list[ZoneData]:
    """One low, wide central coffee table on the rug (Gulf majlis: holds the coffee/dates
    tray). Centred in the open middle."""
    minx, miny, maxx, maxy = analysis.polygon.bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    lat = min(0.30 * (maxx - minx), 180.0)
    fwd = min(0.30 * (maxy - miny), 120.0)
    rect = item_polygon(cx, cy, lat, fwd, 0.0).intersection(analysis.polygon)
    return [
        ZoneData(
            id="z-majlis-coffee_table",
            category="coffee_table",
            polygon=rect if isinstance(rect, Polygon) and not rect.is_empty else analysis.polygon,
            score=0.9,
            rotation_deg=0.0,
            anchor_label="open_centre",
            reason_codes=[R_OPEN_CENTRE],
            kind="free",
            origin=(cx, cy),
            fwd=(0.0, 1.0),
            lat=(1.0, 0.0),
            fwd_len=fwd,
            lat_len=lat,
            place_at_origin=True,
        )
    ]


_ACCESSORY_GAP = 8.0  # min clear gap (cm) an accessory keeps from another accessory


def _accessory_clear(analysis: RoomAnalysis, poly: Polygon, placed: list[PlacedProduct]) -> bool:
    """True if `poly` fits: inside the room, off the seat swing arcs, not overlapping a sofa,
    and keeping a small gap from every already-placed accessory (so a plant never lands on a
    side table, and two pieces never stack in the same corner)."""
    if poly.difference(analysis.polygon.buffer(1.5)).area > 0.01 * poly.area:
        return False
    for arc in analysis.swing_arcs.values():
        if poly.intersection(arc).area > 0.05 * arc.area:
            return False
    for it, p in placed:
        op = item_polygon(it.x, it.y, p.width_cm, p.depth_cm, it.rotation_deg)
        if p.category == "sofa":
            if poly.intersection(op).area > 0.02 * min(poly.area, op.area):
                return False
        elif p.category in ACCESSORY_CATS or p.category == "coffee_table":
            if poly.intersection(op.buffer(_ACCESSORY_GAP)).area > 0.001 * poly.area:
                return False
    return True


def majlis_suggest_pose(analysis: RoomAnalysis, placed: list[PlacedProduct], product, stats):
    """The pose for one product at the next open majlis spot (used by /placement/suggest so
    'alternative spot' / drag re-placement stay on the perimeter, not a family position).
    Imports anchor_pose/settle_pose lazily to avoid a circular import at module load."""
    from app.services.spatial.autofix import settle_pose
    from app.services.spatial.zones import anchor_pose

    def _full():
        c = analysis.usable_area.centroid if not analysis.usable_area.is_empty else analysis.polygon.centroid
        return Pose(x=round(c.x, 1), y=round(c.y, 1), rotation_deg=0.0), None, []

    zones = majlis_zones_for_category(product.category, analysis, placed, stats)
    if not zones:
        return _full()

    # Sofas must stay flush to a wall: walk the ranked slots and take the first the REAL product
    # fits flush & clear (a door-blocked or too-narrow slot is skipped, not forced via rotation).
    if product.category == "sofa":
        placed_sofas = [(i, p) for i, p in placed if p.category == "sofa"]
        for z in zones:
            pose = _sofa_pose_in_zone(analysis, placed_sofas, product, z)
            if pose is not None:
                return pose, z.id, []
        return _full()

    z = zones[0]
    pose = settle_pose(analysis, placed, product, anchor_pose(z, product, analysis))
    return pose, z.id, []


def majlis_zones_for_category(
    category: str, analysis: RoomAnalysis, placed: list[PlacedProduct], stats
) -> list[ZoneData]:
    if category == "sofa":
        return majlis_sofa_zones(analysis, placed, stats)
    if category == "rug":
        return majlis_rug_zones(analysis, placed, stats)
    if category == "coffee_table":
        return majlis_coffee_table_zones(analysis, placed, stats)
    if category in _CORNER_SIZE:
        return majlis_accessory_zones(analysis, placed, category, _CORNER_SIZE[category])
    return []
