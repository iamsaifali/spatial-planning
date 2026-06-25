"""Equivalence comparison between the legacy and recipe planner outputs (shadow mode).

Both paths drive the same deterministic engine, so when equivalent they produce the
SAME proposal_id (which encodes product ids + poses). We still compare field-by-field
so a divergence is reported in human-readable form, and we tolerate sub-cm pose noise
rather than demanding exact float equality.
"""

from dataclasses import dataclass, field

from app.models.api import AssistLayoutResponse

POSE_TOL_CM = 1.0
ROT_TOL_DEG = 0.1


@dataclass
class EquivalenceResult:
    equivalent: bool
    proposal_id_match: bool
    diffs: list[str] = field(default_factory=list)


def _seats(resp: AssistLayoutResponse) -> int:
    return sum(p.product.seating_capacity for p in resp.placements)


def _hard_findings(resp: AssistLayoutResponse) -> list[str]:
    return sorted(f.code for f in resp.findings if f.severity == "error")


def _skipped(resp: AssistLayoutResponse) -> list[tuple[str, str]]:
    return sorted((s.category, s.reason) for s in resp.skipped)


def compare_layouts(legacy: AssistLayoutResponse, recipe: AssistLayoutResponse) -> EquivalenceResult:
    diffs: list[str] = []

    legacy_products = [p.product_id for p in legacy.placements]
    recipe_products = [p.product_id for p in recipe.placements]
    legacy_cats = [p.category for p in legacy.placements]
    recipe_cats = [p.category for p in recipe.placements]

    if len(legacy.placements) != len(recipe.placements):
        diffs.append(f"placement_count {len(legacy.placements)} != {len(recipe.placements)}")
    if legacy_cats != recipe_cats:
        diffs.append(f"categories {legacy_cats} != {recipe_cats}")
    if legacy_products != recipe_products:
        diffs.append(f"product_ids {legacy_products} != {recipe_products}")
    if _skipped(legacy) != _skipped(recipe):
        diffs.append(f"skipped {_skipped(legacy)} != {_skipped(recipe)}")
    if _hard_findings(legacy) != _hard_findings(recipe):
        diffs.append(f"hard_findings {_hard_findings(legacy)} != {_hard_findings(recipe)}")
    if _seats(legacy) != _seats(recipe):
        diffs.append(f"total_seats {_seats(legacy)} != {_seats(recipe)}")

    # pose comparison only where product order already aligns (else it's already a diff)
    if legacy_products == recipe_products:
        for a, b in zip(legacy.placements, recipe.placements):
            if (
                abs(a.pose.x - b.pose.x) > POSE_TOL_CM
                or abs(a.pose.y - b.pose.y) > POSE_TOL_CM
                or abs(a.pose.rotation_deg - b.pose.rotation_deg) > ROT_TOL_DEG
            ):
                diffs.append(f"pose[{a.product_id}] {a.pose} != {b.pose}")
                break

    return EquivalenceResult(
        equivalent=not diffs,
        proposal_id_match=legacy.proposal_id == recipe.proposal_id,
        diffs=diffs,
    )
