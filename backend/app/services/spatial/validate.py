"""Placement validation: findings are advisory; the user may always keep anyway."""

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from app.models.geometry import PlacedItem
from app.models.products import CATEGORY_LABELS, Product
from app.models.validation import (
    BLOCKS_DOOR_SWING,
    BLOCKS_WALKWAY,
    BLOCKS_WINDOW,
    CLEARANCE_TOO_FAR,
    CLEARANCE_TOO_TIGHT,
    DOMINATES_ROOM,
    FRONT_BLOCKED,
    NARROWS_WALKWAY,
    OUT_OF_BOUNDS,
    OVERLAP_ITEM,
    TV_TOO_CLOSE,
    Finding,
)
from app.services.spatial.core import CorridorData, RoomAnalysis
from app.services.spatial.geometry_utils import (
    add,
    dot,
    front_vector,
    item_polygon,
    pieces_of,
    poly_pts,
    quad,
    sub,
    unit,
    width_axis,
)

PlacedProduct = tuple[PlacedItem, Product]

OOB_TOLERANCE_RATIO = 0.01
OVERLAP_RATIO = 0.02
SWING_RATIO = 0.05
SEATING = {"sofa", "accent_chair"}
FRONT_STRIP = {"tv_unit": 80.0, "storage": 60.0}


def build_poly(item: PlacedItem, product: Product) -> Polygon:
    return item_polygon(item.x, item.y, product.width_cm, product.depth_cm, item.rotation_deg)


def _label(product: Product) -> str:
    return CATEGORY_LABELS.get(product.category, product.category)


def _front_strip_poly(item: PlacedItem, product: Product, depth: float) -> Polygon:
    f = front_vector(item.rotation_deg)
    w = width_axis(item.rotation_deg)
    front_center = add((item.x, item.y), f, product.depth_cm / 2.0)
    half = product.width_cm / 2.0
    return quad(
        add(front_center, w, -half),
        add(front_center, w, half),
        add(add(front_center, w, half), f, depth),
        add(add(front_center, w, -half), f, depth),
    )


def corridor_blocked(corridor: CorridorData, blockers) -> tuple[bool, float]:
    """(fully blocked?, overlap ratio). Connectivity test, not mere intersection."""
    overlap = corridor.polygon.intersection(blockers).area / max(corridor.polygon.area, 1e-9)
    if overlap <= 1e-6:
        return False, 0.0
    remaining = corridor.polygon.difference(blockers)
    a_buf = Point(corridor.a).buffer(15.0)

    if corridor.to_label == "center":
        # The entry->center corridor guards stepping INTO the room. Its far end
        # is the room's most interior point, where coffee tables and rugs
        # legitimately live - so require walkable depth from the door, not a
        # clear endpoint.
        for piece in pieces_of(remaining):
            if piece.intersects(a_buf) and piece.area >= 0.35 * corridor.polygon.area:
                return False, overlap
        return True, overlap

    # door-to-door paths must stay truly connected
    b_buf = Point(corridor.b).buffer(15.0)
    for piece in pieces_of(remaining):
        if piece.intersects(a_buf) and piece.intersects(b_buf):
            return False, overlap
    return True, overlap


def must_fix_only(
    analysis: RoomAnalysis,
    other_polys: list[tuple[PlacedItem, Product, Polygon]],
    product: Product,
    poly: Polygon,
    room_buffered: Polygon,
) -> bool:
    """Fast predicate used by autofix: True when pose has no error-level issues."""
    if poly.difference(room_buffered).area > OOB_TOLERANCE_RATIO * poly.area:
        return False
    if not product.is_walkable:
        for _i, p, op in other_polys:
            if p.is_walkable:
                continue
            inter = poly.intersection(op)
            if not inter.is_empty and inter.area > OVERLAP_RATIO * min(poly.area, op.area):
                return False
    for arc in analysis.swing_arcs.values():
        if poly.intersection(arc).area > SWING_RATIO * arc.area:
            return False
    if not product.is_walkable and analysis.corridors:
        blockers = unary_union(
            [poly] + [op for _i, p, op in other_polys if not p.is_walkable]
        )
        for corridor in analysis.corridors:
            blocked, _ = corridor_blocked(corridor, blockers)
            if blocked:
                return False
    return True


def validate_item(
    analysis: RoomAnalysis,
    placed: list[PlacedProduct],
    item: PlacedItem,
    product: Product,
) -> list[Finding]:
    findings: list[Finding] = []
    poly = build_poly(item, product)
    others = [(i, p, build_poly(i, p)) for i, p in placed if i.instance_id != item.instance_id]

    # Out of bounds
    outside = poly.difference(analysis.polygon.buffer(1.5))
    if outside.area > OOB_TOLERANCE_RATIO * poly.area:
        pct = round(100.0 * outside.area / poly.area)
        findings.append(
            Finding(
                code=OUT_OF_BOUNDS,
                severity="error",
                message=f"The {_label(product).lower()} extends outside the room ({pct}% of it is beyond the walls).",
                item_instance_id=item.instance_id,
            )
        )

    # Overlaps
    if not product.is_walkable:
        for other_item, other_product, other_poly in others:
            if other_product.is_walkable:
                continue
            inter = poly.intersection(other_poly)
            if not inter.is_empty and inter.area > OVERLAP_RATIO * min(poly.area, other_poly.area):
                findings.append(
                    Finding(
                        code=OVERLAP_ITEM,
                        severity="error",
                        message=f"The {_label(product).lower()} overlaps the {_label(other_product).lower()}.",
                        item_instance_id=item.instance_id,
                        other_instance_id=other_item.instance_id,
                    )
                )

    # Door swings
    for door_id, arc in analysis.swing_arcs.items():
        inter = poly.intersection(arc)
        if inter.area > SWING_RATIO * arc.area:
            findings.append(
                Finding(
                    code=BLOCKS_DOOR_SWING,
                    severity="error",
                    message=f"The {_label(product).lower()} blocks the door from opening fully.",
                    item_instance_id=item.instance_id,
                    geometry=poly_pts(arc),
                )
            )

    # Walkways
    if not product.is_walkable and analysis.corridors:
        blockers = unary_union([poly] + [op for _i, p, op in others if not p.is_walkable])
        for corridor in analysis.corridors:
            blocked, overlap = corridor_blocked(corridor, blockers)
            own_overlap = poly.intersection(corridor.polygon).area / max(corridor.polygon.area, 1e-9)
            if own_overlap <= 0.01:
                continue
            if blocked:
                findings.append(
                    Finding(
                        code=BLOCKS_WALKWAY,
                        severity="warning",
                        message="This placement blocks the walkway from the door. "
                        "I can move it slightly to keep the path clear.",
                        item_instance_id=item.instance_id,
                        geometry=poly_pts(corridor.polygon),
                    )
                )
                break
            if own_overlap > 0.30:
                findings.append(
                    Finding(
                        code=NARROWS_WALKWAY,
                        severity="info",
                        message="This placement narrows the walkway; there is still room to pass.",
                        item_instance_id=item.instance_id,
                    )
                )
                break

    # Windows (tall items only)
    for win_id, (strip, sill) in analysis.window_strips.items():
        if product.height_cm > sill and poly.intersection(strip).area > 400.0:
            findings.append(
                Finding(
                    code=BLOCKS_WINDOW,
                    severity="warning",
                    message=f"The {_label(product).lower()} ({product.height_cm:.0f} cm tall) "
                    f"would block light from the window (sill at {sill:.0f} cm).",
                    item_instance_id=item.instance_id,
                )
            )
            break

    findings.extend(_pair_findings(item, product, poly, others))

    # Dominates room
    if analysis.usable_cm2 > 0 and poly.area > 0.35 * analysis.usable_cm2:
        findings.append(
            Finding(
                code=DOMINATES_ROOM,
                severity="info",
                message=f"This {_label(product).lower()} takes up a large share of the floor; "
                "a smaller size could make the room feel more open.",
                item_instance_id=item.instance_id,
            )
        )
    return findings


def _pair_findings(
    item: PlacedItem,
    product: Product,
    poly: Polygon,
    others: list[tuple[PlacedItem, Product, Polygon]],
) -> list[Finding]:
    findings: list[Finding] = []
    cat = product.category

    for other_item, other_product, other_poly in others:
        ocat = other_product.category
        pair = {cat, ocat}
        d = poly.distance(other_poly)

        if pair == {"sofa", "coffee_table"}:
            sofa_item, sofa_prod = (item, product) if cat == "sofa" else (other_item, other_product)
            table_item = other_item if cat == "sofa" else item
            f = front_vector(sofa_item.rotation_deg)
            to_table = unit(*sub((table_item.x, table_item.y), (sofa_item.x, sofa_item.y)))
            in_front = dot(f, to_table) > 0.5
            if in_front and 0.0 < d < 35.0:
                findings.append(
                    Finding(
                        code=CLEARANCE_TOO_TIGHT,
                        severity="warning",
                        message=f"Only {d:.0f} cm between sofa and coffee table - "
                        "40-45 cm makes it comfortable to walk and reach.",
                        item_instance_id=item.instance_id,
                        other_instance_id=other_item.instance_id,
                    )
                )
            elif in_front and d > 75.0:
                findings.append(
                    Finding(
                        code=CLEARANCE_TOO_FAR,
                        severity="info",
                        message=f"The coffee table sits {d:.0f} cm from the sofa - "
                        "within 45-60 cm keeps drinks in easy reach.",
                        item_instance_id=item.instance_id,
                        other_instance_id=other_item.instance_id,
                    )
                )
        elif cat in SEATING and ocat in SEATING and 0.0 < d < 45.0:
            findings.append(
                Finding(
                    code=CLEARANCE_TOO_TIGHT,
                    severity="warning",
                    message=f"Seats are only {d:.0f} cm apart; 45 cm or more avoids a cramped feel.",
                    item_instance_id=item.instance_id,
                    other_instance_id=other_item.instance_id,
                )
            )
        elif pair == {"sofa", "tv_unit"}:
            sofa_item = item if cat == "sofa" else other_item
            tv_item = other_item if cat == "sofa" else item
            f = front_vector(sofa_item.rotation_deg)
            to_tv = unit(*sub((tv_item.x, tv_item.y), (sofa_item.x, sofa_item.y)))
            if dot(f, to_tv) > 0.5 and d < 200.0:
                findings.append(
                    Finding(
                        code=TV_TOO_CLOSE,
                        severity="warning",
                        message=f"The TV unit is {d:.0f} cm from the sofa - "
                        "250-400 cm is a comfortable viewing distance.",
                        item_instance_id=item.instance_id,
                        other_instance_id=other_item.instance_id,
                    )
                )

        # Front strips: storage/TV need open space to be usable
        for strip_item, strip_product, blocker_item, blocker_product, blocker_poly in (
            (item, product, other_item, other_product, other_poly),
            (other_item, other_product, item, product, poly),
        ):
            depth = FRONT_STRIP.get(strip_product.category)
            if depth is None or blocker_product.is_walkable:
                continue
            strip = _front_strip_poly(strip_item, strip_product, depth)
            if strip.intersection(blocker_poly).area > 0.25 * strip.area:
                findings.append(
                    Finding(
                        code=FRONT_BLOCKED,
                        severity="warning",
                        message=f"The {_label(blocker_product).lower()} sits right in front of the "
                        f"{_label(strip_product).lower()}, making it hard to use.",
                        item_instance_id=item.instance_id,
                        other_instance_id=other_item.instance_id,
                    )
                )
                break

    # de-duplicate identical (code, other) pairs
    seen: set[tuple[str, str | None]] = set()
    unique: list[Finding] = []
    for f in findings:
        key = (f.code, f.other_instance_id)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique
