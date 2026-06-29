"""Compose a complete, shoppable Majlis layout: real catalog products for the perimeter
seating + accessories, with honest seat capacity.

Design choice (cohesive majlis): ONE sofa model is tiled around the whole perimeter, so the
seating matches all the way round - and because the packer uses that product's real width,
the geometry is exact. Accessories pick the best product for each pool and are dropped if a
product's real footprint would collide.
"""

from dataclasses import dataclass

from app.models.geometry import PlacedItem, Room
from app.models.preferences import Preferences
from app.models.products import Product
from app.services.catalog import get_repository
from app.services.majlis.accessories import WALKABLE, build_accessories
from app.services.majlis.layout import fill_perimeter, total_seats
from app.services.spatial.analyze import analyze_room
from app.services.spatial.core import RoomAnalysis
from app.services.spatial.geometry_utils import item_polygon

# preferred width band for the tiled majlis sofa (a comfortable 3-seater)
SOFA_BAND = (190.0, 240.0)


@dataclass
class MajlisResult:
    placed_items: list[PlacedItem]
    seats: int
    note: str


def _primary_sofa(repo, prefs: Preferences) -> Product | None:
    pool = repo.pool_for("sofa", prefs)
    if not pool:
        return None
    return next((p for p in pool if SOFA_BAND[0] <= p.width_cm <= SOFA_BAND[1]), pool[0])


def _best(repo, prefs: Preferences, category: str) -> Product | None:
    pool = repo.pool_for(category, prefs)
    return pool[0] if pool else None


def _accessory_clear(analysis: RoomAnalysis, poly, sofa_polys, walkable: bool) -> bool:
    if poly.difference(analysis.polygon.buffer(1.5)).area > 0.01 * poly.area:
        return False
    if walkable:
        return True  # a rug may sit under the sofa fronts
    for arc in analysis.swing_arcs.values():
        if poly.intersection(arc).area > 0.05 * arc.area:
            return False
    for sp in sofa_polys:
        inter = poly.intersection(sp)
        if not inter.is_empty and inter.area > 0.02 * min(poly.area, sp.area):
            return False
    return True


def generate_majlis(room: Room, prefs: Preferences) -> MajlisResult:
    """Full majlis placement (sofas + accessories) as shoppable PlacedItems + capacity."""
    repo = get_repository()
    analysis = analyze_room(room)

    sofa = _primary_sofa(repo, prefs)
    if sofa is None:
        return MajlisResult([], 0, "No sofas are available to build a majlis.")

    # tile the one sofa model around every wall (uniform; packer uses its real width)
    seats = fill_perimeter(analysis, module_widths=(sofa.width_cm,), depth=sofa.depth_cm)
    items: list[PlacedItem] = []
    for i, s in enumerate(seats):
        items.append(
            PlacedItem(
                instance_id=f"majlis-sofa-{i}", product_id=sofa.id,
                x=s.x, y=s.y, rotation_deg=s.rotation_deg, zone_id=f"z-majlis-w{s.wall_index}",
            )
        )

    sofa_polys = [item_polygon(s.x, s.y, sofa.width_cm, sofa.depth_cm, s.rotation_deg) for s in seats]

    # accessories: pick the best product per category, keep it only if its real footprint fits
    for j, acc in enumerate(build_accessories(analysis, seats)):
        product = _best(repo, prefs, acc.category)
        if product is None:
            continue
        poly = item_polygon(acc.x, acc.y, product.width_cm, product.depth_cm, acc.rotation_deg)
        if not _accessory_clear(analysis, poly, sofa_polys, acc.category in WALKABLE):
            continue
        items.append(
            PlacedItem(
                instance_id=f"majlis-{acc.category}-{j}", product_id=product.id,
                x=acc.x, y=acc.y, rotation_deg=acc.rotation_deg, zone_id=f"z-majlis-{acc.category}",
            )
        )

    total = total_seats(seats)
    note = (
        f"Majlis seating for about {total} around the room - sofas line every wall facing "
        f"the open centre."
        if total
        else "This room is too small to lay out a majlis - try a larger room."
    )
    return MajlisResult(items, total, note)
