"""Majlis-specific layout validation.

Reuses the low-level geometry of the spatial engine but a DIFFERENT rule set than the
family room: the family TV-sightline / clearance / dominates-room rules do not apply to a
majlis. We keep the universal error checks (out-of-bounds, sofa overlap, blocked door
swing) and add the majlis essentials: the centre must stay open, and adjacent-wall sofas
must not collide at the corners.
"""

from shapely.geometry import Polygon
from shapely.ops import unary_union

from app.models.validation import (
    BLOCKS_DOOR_SWING,
    OUT_OF_BOUNDS,
    OVERLAP_ITEM,
    Finding,
)
from app.services.majlis.layout import SeatPlacement
from app.services.spatial.core import RoomAnalysis

MAJLIS_CENTER_BLOCKED = "MAJLIS_CENTER_BLOCKED"

OOB_TOLERANCE_RATIO = 0.01
OVERLAP_RATIO = 0.02
SWING_RATIO = 0.05
# The open-centre island is the room inset by the seating depth + this walkway margin;
# perimeter sofas sit outside it, so only a sofa that drifts into the middle trips the rule.
CENTER_MARGIN_CM = 50.0


def validate_majlis(analysis: RoomAnalysis, placements: list[SeatPlacement]) -> list[Finding]:
    findings: list[Finding] = []
    polys = [(i, p.polygon()) for i, p in enumerate(placements)]
    room_buffered = analysis.polygon.buffer(1.5)

    # out of bounds
    for i, poly in polys:
        if poly.difference(room_buffered).area > OOB_TOLERANCE_RATIO * poly.area:
            findings.append(_f(OUT_OF_BOUNDS, "error", f"Sofa {i} extends outside the room.", i))

    # sofa-sofa overlap (incl. corner collisions between adjacent walls)
    for a in range(len(polys)):
        for b in range(a + 1, len(polys)):
            inter = polys[a][1].intersection(polys[b][1])
            if not inter.is_empty and inter.area > OVERLAP_RATIO * min(polys[a][1].area, polys[b][1].area):
                findings.append(_f(OVERLAP_ITEM, "error", f"Sofas {a} and {b} overlap.", a, b))

    # door swings
    for poly_i, poly in polys:
        for arc in analysis.swing_arcs.values():
            if poly.intersection(arc).area > SWING_RATIO * arc.area:
                findings.append(_f(BLOCKS_DOOR_SWING, "error", f"Sofa {poly_i} blocks a door from opening.", poly_i))
                break

    # centre must stay open: no seating inside the central island
    center = _center_island(analysis, placements)
    if center is not None and not center.is_empty:
        seating = unary_union([p for _i, p in polys]) if polys else None
        if seating is not None and seating.intersection(center).area > 0.02 * center.area:
            findings.append(
                Finding(
                    code=MAJLIS_CENTER_BLOCKED,
                    severity="warning",
                    message="Seating intrudes on the open centre of the majlis.",
                    item_instance_id="majlis",
                )
            )
    return findings


def _center_island(analysis: RoomAnalysis, placements: list[SeatPlacement]) -> Polygon | None:
    """The open central zone = the room inset by the seating depth + a walkway margin.
    Perimeter sofas sit outside it; a sofa reaching inside means the centre is being
    crowded (a real defect, e.g. a stray non-perimeter seat)."""
    seat_depth = max((p.depth_cm for p in placements), default=95.0)
    island = analysis.polygon.buffer(-(seat_depth + CENTER_MARGIN_CM))
    return island if not island.is_empty else None


def _f(code: str, severity: str, message: str, i: int, j: int | None = None) -> Finding:
    return Finding(
        code=code, severity=severity, message=message,
        item_instance_id=f"sofa-{i}", other_instance_id=(f"sofa-{j}" if j is not None else None),
    )


def error_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "error"]
