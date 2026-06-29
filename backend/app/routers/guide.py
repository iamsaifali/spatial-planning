import asyncio

from fastapi import APIRouter

from app.errors import AppError
from app.models.api import PlanRequest, PlanResponse, StepRequest
from app.models.geometry import Pose
from app.models.recommend import (
    NOTICE_NO_FIT,
    NOTICE_SKIPPED_TIGHT,
    Guidance,
    NoFit,
    Recommendation,
    StepResponse,
    StepsResponse,
    WhyItFits,
)
from app.routers._common import resolve_placed, wall_label, zone_guidance_facts
from app.services.ai import copy_service
from app.services.catalog import get_repository
from app.services.guide.flow import require_step, steps_from_plan, steps_with_status
from app.services.majlis import plan as majlis_plan
from app.services.majlis.zones import majlis_zones_for_category
from app.services.plan import director
from app.services.recommend.selector import Candidate, select_recommendations
from app.services.spatial.analyze import analyze_room
from app.services.spatial.autofix import settle_pose
from app.services.spatial.core import RoomAnalysis
from app.services.spatial.geometry_utils import item_polygon
from app.services.spatial.zones import (
    ESSENTIAL_CATEGORIES,
    anchor_pose,
    drop_cramped_zones,
    zones_for_category,
)

router = APIRouter(prefix="/guide", tags=["guide"])


@router.post("/steps", response_model=StepsResponse)
def steps(req: StepRequest) -> StepsResponse:
    placed = resolve_placed(req.placed_items)
    return StepsResponse(steps=steps_with_status(placed))


def _why_facts(candidate: Candidate, analysis: RoomAnalysis) -> dict:
    product = candidate.product
    facts: dict = {
        "category": product.category,
        "product_name": product.name,
        "width_cm": product.width_cm,
        "depth_cm": product.depth_cm,
        "price": product.price,
        "rating": product.rating,
        "style_tags": product.style_tags,
        **candidate.facts,
    }
    if candidate.zone.kind == "wall_band" and candidate.zone.wall_index is not None:
        facts["wall_label"] = wall_label(analysis.walls[candidate.zone.wall_index])
    facts["notices"] = candidate.notices
    return facts


@router.post("/step/{step_key}", response_model=StepResponse)
async def step(step_key: str, req: StepRequest) -> StepResponse:
    step_def = require_step(step_key)
    placed = resolve_placed(req.placed_items)
    analysis = analyze_room(req.room)
    repo = get_repository()
    stats = repo.category_stats()

    is_majlis = req.preferences.room_type == "majlis"
    skipped_for_space = False
    if is_majlis:
        # Majlis: same guided UX, but positions come from the perimeter engine (next open
        # wall slot / centre / corner). No LLM, no walkway gating.
        layout, _src = majlis_plan.get_majlis_plan(req.room, req.preferences, placed)
        plan_item = next((it for it in layout.items if it.category == step_def.category), None)
        step_quantity = plan_item.quantity if plan_item else 1
        zones = majlis_zones_for_category(step_def.category, analysis, placed, stats)
    else:
        # The cached plan (keyed by room+prefs hash) tells us how many of this category to
        # place; no extra LLM call on a warm cache. Recommendations don't need the plan, so
        # if planning is unavailable (LLM-only) we still serve the step with quantity 1.
        try:
            layout, _plan_source = await director.get_plan(req.room, req.preferences, placed)
            plan_item = next((it for it in layout.items if it.category == step_def.category), None)
            step_quantity = plan_item.quantity if plan_item else 1
        except AppError:
            step_quantity = 1

        # step_quantity for the sofa step is the planned sofa count; the sofa zone generator
        # uses it to centre an L/U cluster (arms extend forward) instead of just the primary.
        zones = zones_for_category(step_def.category, analysis, placed, stats, n_planned=step_quantity)
        # quality-gate non-essentials: a 2nd chair / extra decor is SKIPPED rather than
        # jammed into a walkway when the room is tight. Essentials are never gated.
        if step_def.category not in ESSENTIAL_CATEGORIES:
            clean = drop_cramped_zones(analysis, zones)
            skipped_for_space = bool(zones) and not clean
            zones = clean
    pool = repo.pool_for(step_def.category, req.preferences)
    result = select_recommendations(step_def.category, zones, req.preferences, placed, repo, products=pool)

    guidance_facts = zone_guidance_facts(step_def.category, analysis, zones, placed)

    # placed non-walkable footprints - a recommendation must never land on top of one.
    placed_polys = [
        item_polygon(it.x, it.y, p.width_cm, p.depth_cm, it.rotation_deg)
        for it, p in placed
        if not p.is_walkable
    ]

    def _overlaps_placed(pose: Pose, product) -> bool:
        poly = item_polygon(pose.x, pose.y, product.width_cm, product.depth_cm, pose.rotation_deg)
        return any(poly.intersection(op).area > 400.0 for op in placed_polys)

    async def build_rec(rank: int, candidate: Candidate) -> tuple[Recommendation, bool]:
        copy, source = await copy_service.generate("why_it_fits", _why_facts(candidate, analysis))
        raw_pose = anchor_pose(candidate.zone, candidate.product, analysis)
        pose = settle_pose(analysis, placed, candidate.product, raw_pose)
        rec = Recommendation(
            rank=rank,
            product=candidate.product,
            why_it_fits=WhyItFits(**copy, copy_source=source),  # type: ignore[arg-type]
            suggested_pose=Pose(x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg),
            zone_id=candidate.zone.id,
            fit_facts=candidate.facts,
            notices=candidate.notices,
        )
        # a non-essential whose settled pose still overlaps a placed item has no clean
        # spot left - drop it rather than recommend placing on top of something.
        bad = step_def.category not in ESSENTIAL_CATEGORIES and _overlaps_placed(pose, candidate.product)
        return rec, bad

    guidance_task = copy_service.generate("guide", guidance_facts)
    rec_tasks = [build_rec(i, cand) for i, cand in enumerate(result.recommendations)]
    guidance_result, *rec_pairs = await asyncio.gather(guidance_task, *rec_tasks)
    guidance_copy, guidance_source = guidance_result
    recommendations = [r for r, bad in rec_pairs if not bad]
    for rank, r in enumerate(recommendations):  # keep ranks contiguous after filtering
        r.rank = rank
    dropped_overlap = bool(rec_pairs) and not recommendations

    no_fit = None
    if not recommendations:
        if skipped_for_space or dropped_overlap:
            reason = NOTICE_SKIPPED_TIGHT
        else:
            reason = str(result.no_fit_hints.get("reason", NOTICE_NO_FIT))
        no_fit = NoFit(reason=reason, hints=result.no_fit_hints or {"reason": reason})

    return StepResponse(
        analysis_hash=analysis.analysis_hash,
        step_key=step_key,
        guidance=Guidance(
            message=guidance_copy.get("message", ""),
            tip=guidance_copy.get("tip"),
            reason_codes=guidance_facts.get("reason_codes", []),
            copy_source=guidance_source,  # type: ignore[arg-type]
        ),
        zones=[z.to_model() for z in zones],
        recommendations=list(recommendations),
        no_fit=no_fit,
        quantity=step_quantity,
    )


@router.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest) -> PlanResponse:
    placed = resolve_placed(req.placed_items)
    # room_type dispatch: "majlis" routes to the separate Majlis engine; everything else
    # (default "living_room") falls through to the unchanged family planner.
    if req.preferences.room_type == "majlis":
        layout, source = majlis_plan.get_majlis_plan(req.room, req.preferences, placed)
    else:
        layout, source = await director.get_plan(req.room, req.preferences, placed)
    steps = steps_from_plan(layout, placed)
    return PlanResponse(plan=layout, steps=steps, plan_source=source)  # type: ignore[arg-type]
