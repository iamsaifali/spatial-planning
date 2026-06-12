"""Shared 2-D helpers. Screen coordinates: x right, y DOWN, all cm.

Rotation convention (pinned by tests): at 0 deg an item's width lies along +x
and its front faces +y (down). Positive rotation appears CLOCKWISE on screen
because the y axis is flipped relative to math coordinates, which makes
shapely's positive (math-CCW) rotation render clockwise.
"""

import math

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry

Vec = tuple[float, float]


def unit(vx: float, vy: float) -> Vec:
    n = math.hypot(vx, vy)
    if n < 1e-9:
        return (0.0, 0.0)
    return (vx / n, vy / n)


def add(a: Vec, b: Vec, scale: float = 1.0) -> Vec:
    return (a[0] + b[0] * scale, a[1] + b[1] * scale)


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def dist(a: Vec, b: Vec) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def perp(v: Vec) -> Vec:
    return (-v[1], v[0])


def rotate_vec(v: Vec, deg: float) -> Vec:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def front_vector(rotation_deg: float) -> Vec:
    """Unit vector the item front faces at the given rotation."""
    r = math.radians(rotation_deg)
    return (-math.sin(r), math.cos(r))


def width_axis(rotation_deg: float) -> Vec:
    """Unit vector along the item's width at the given rotation."""
    r = math.radians(rotation_deg)
    return (math.cos(r), math.sin(r))


def rotation_for_normal(n: Vec) -> float:
    """Rotation whose front_vector equals the given unit vector."""
    return math.degrees(math.atan2(-n[0], n[1])) % 360.0


def item_polygon(cx: float, cy: float, width: float, depth: float, rotation_deg: float) -> Polygon:
    b = box(cx - width / 2.0, cy - depth / 2.0, cx + width / 2.0, cy + depth / 2.0)
    if rotation_deg % 360.0 == 0.0:
        return b
    return affinity.rotate(b, rotation_deg, origin=(cx, cy))


def quad(p1: Vec, p2: Vec, p3: Vec, p4: Vec) -> Polygon:
    return Polygon([p1, p2, p3, p4])


def largest_piece(geom: BaseGeometry | None) -> Polygon | None:
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda g: g.area)
    pieces = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    return max(pieces, key=lambda g: g.area) if pieces else None


def pieces_of(geom: BaseGeometry | None) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]


def poly_pts(poly: Polygon) -> list[tuple[float, float]]:
    """Exterior ring as rounded point list (closing vertex dropped)."""
    return [(round(x, 1), round(y, 1)) for x, y in poly.exterior.coords[:-1]]


def line_pts(line: LineString) -> list[tuple[float, float]]:
    return [(round(x, 1), round(y, 1)) for x, y in line.coords]


def extent_along(poly: Polygon, origin: Vec, direction: Vec) -> tuple[float, float]:
    """Min/max projection of polygon vertices onto a direction from origin."""
    lo, hi = math.inf, -math.inf
    for x, y in poly.exterior.coords:
        t = (x - origin[0]) * direction[0] + (y - origin[1]) * direction[1]
        lo, hi = min(lo, t), max(hi, t)
    return lo, hi


def first_boundary_hit(poly: Polygon, start: Vec, direction: Vec, max_dist: float = 5000.0) -> float:
    """Distance from start to the first room boundary along direction."""
    ray = LineString([start, add(start, direction, max_dist)])
    hit = ray.intersection(poly.exterior)
    if hit.is_empty:
        return max_dist
    pts: list[Point] = []
    if isinstance(hit, Point):
        pts = [hit]
    else:
        for g in getattr(hit, "geoms", []):
            if isinstance(g, Point):
                pts.append(g)
            elif isinstance(g, LineString):
                pts.extend(Point(c) for c in g.coords)
    if not pts:
        return max_dist
    return min(p.distance(Point(start)) for p in pts)


def subtract_intervals(
    length: float, blocks: list[tuple[float, float]], min_keep: float = 1.0
) -> list[tuple[float, float]]:
    """1-D subtraction of [a,b) blocks from [0,length]."""
    clipped = sorted(
        (max(0.0, a), min(length, b)) for a, b in blocks if b > 0 and a < length
    )
    out: list[tuple[float, float]] = []
    cur = 0.0
    for a, b in clipped:
        if a > cur + 1e-9:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < length - 1e-9:
        out.append((cur, length))
    return [(a, b) for a, b in out if b - a >= min_keep]


def merge_intervals(blocks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not blocks:
        return []
    blocks = sorted(blocks)
    out = [blocks[0]]
    for a, b in blocks[1:]:
        la, lb = out[-1]
        if a <= lb + 1e-9:
            out[-1] = (la, max(lb, b))
        else:
            out.append((a, b))
    return out
