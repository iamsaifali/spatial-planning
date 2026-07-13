import asyncio


from spatial_planning.models.api import StepRequest
from spatial_planning.models.geometry import Pose
from spatial_planning.models.recommend import (
    NOTICE_NO_FIT,
    EmptySlot,
    Guidance,
    Recommendation,
    StepResponse,
    StepsResponse,
    WhyItFits,
)
from spatial_planning.handlers._common import resolve_placed, wall_label, zone_guidance_facts
from spatial_planning.services.ai import copy_service
from spatial_planning.services.catalog import get_repository
from spatial_planning.services.guide.flow import require_step, steps_with_status
from spatial_planning.services.recommend.selector import Candidate, select_slots
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.autofix import settle_pose
from spatial_planning.services.spatial.core import RoomAnalysis
from spatial_planning.services.spatial.zones import anchor_pose, zones_for_category



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


async def step(step_key: str, req: StepRequest) -> StepResponse:
    step_def = require_step(step_key)
    placed = resolve_placed(req.placed_items)
    analysis = analyze_room(req.room)
    repo = get_repository()
    stats = repo.category_stats()

    zones = zones_for_category(step_def.category, analysis, placed, stats)
    result = select_slots(step_def.category, zones, req.preferences, placed, repo)

    guidance_facts = zone_guidance_facts(step_def.category, analysis, zones, placed)

    slots: list[tuple[str, Candidate | None]] = [
        ("best_match", result.best),
        ("budget", result.budget),
        ("premium", result.premium),
    ]

    async def build_rec(slot: str, candidate: Candidate) -> Recommendation:
        copy, source = await copy_service.generate("why_it_fits", _why_facts(candidate, analysis))
        raw_pose = anchor_pose(candidate.zone, candidate.product, analysis)
        pose = settle_pose(analysis, placed, candidate.product, raw_pose)
        return Recommendation(
            slot=slot,  # type: ignore[arg-type]
            product=candidate.product,
            why_it_fits=WhyItFits(**copy, copy_source=source),  # type: ignore[arg-type]
            suggested_pose=Pose(x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg),
            zone_id=candidate.zone.id,
            fit_facts=candidate.facts,
            notices=candidate.notices,
        )

    guidance_task = copy_service.generate("guide", guidance_facts)
    rec_tasks = [build_rec(slot, cand) for slot, cand in slots if cand is not None]
    guidance_result, *recommendations = await asyncio.gather(guidance_task, *rec_tasks)
    guidance_copy, guidance_source = guidance_result

    empty_slots = [
        EmptySlot(slot=slot, reason=str(result.no_fit_hints.get("reason", NOTICE_NO_FIT)), hints=result.no_fit_hints)  # type: ignore[arg-type]
        for slot, cand in slots
        if cand is None
    ]

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
        empty_slots=empty_slots,
    )
