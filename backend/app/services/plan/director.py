"""The LLM Layout Director: preferences + room facts -> a LayoutPlan.

The LLM decides ONLY content - which categories belong, how many of each, a
placement priority, and an essential/non_essential tier. It never emits coordinates,
products, or arrangement intent (it sees only a per-category catalog summary).
Output is schema-constrained, then validated/clamped by _coerce_plan.

Planning is LLM-ONLY: there is no heuristic fallback. If the LLM is unavailable
(no API key) or returns nothing usable, get_plan raises PLAN_UNAVAILABLE. Callers
that merely *consume* a plan (guide step quantity, summary completeness) catch that
and degrade; the /guide/plan endpoint surfaces it.
"""

import hashlib
import json
import logging
from typing import get_args

from app.errors import PLAN_UNAVAILABLE, AppError
from app.models.geometry import Room
from app.models.plan import LayoutPlan, PlanItem
from app.models.preferences import Preferences
from app.models.products import Category
from app.services.ai import copy_service
from app.services.catalog import get_repository
from app.services.plan import archetypes, capacity
from app.services.spatial.analyze import analyze_room
from app.services.spatial.cache import LRUCache
from app.services.spatial.core import RoomAnalysis

logger = logging.getLogger("zory.plan")

_VALID_CATEGORIES = set(get_args(Category)) - {"custom"}
_VALID_TIERS = {"essential", "non_essential"}
# Family essentials: always present, always essential, regardless of LLM output.
ESSENTIAL_CATEGORIES = ("sofa", "tv_unit", "rug", "coffee_table")

_plan_cache: LRUCache[tuple[LayoutPlan, str]] = LRUCache(128)


def _prefs_hash(prefs: Preferences) -> str:
    raw = json.dumps(prefs.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _wall_facts(analysis: RoomAnalysis) -> list[dict]:
    """Per-wall geometry the director reasons about: length, longest clear run,
    focal flag, and the openings (doors/windows) sitting on each wall."""
    walls = []
    for w in analysis.walls:
        clear_run = max((b - a for a, b in w.clear_floor), default=0.0)
        walls.append({
            "index": w.index,
            "length_cm": round(w.length),
            "clear_run_cm": round(clear_run),
            "is_focal": w.is_focal,
            "is_longest_clear": w.is_longest_clear,
            "openings": [
                {"type": o.kind, "start_cm": round(o.a), "width_cm": round(o.b - o.a)}
                for o in w.openings
            ],
        })
    return walls


def _facts(room: Room, prefs: Preferences, analysis: RoomAnalysis, summary: dict, placed) -> dict:
    minx, miny, maxx, maxy = analysis.polygon.bounds
    return {
        "purpose": prefs.room_purpose or "family",
        "room_area_m2": round(analysis.area_cm2 / 10_000.0, 1),
        "room_w_cm": round(maxx - minx),
        "room_d_cm": round(maxy - miny),
        "has_focal_wall": analysis.focal_wall_index is not None,
        "focal_wall_index": analysis.focal_wall_index,
        "walls": _wall_facts(analysis),
        "doors": len(room.doors),
        "windows": len(room.windows),
        "styles": list(prefs.styles),
        "colors": list(prefs.colors),
        "seating_capacity": capacity.target_capacity(prefs),
        "seating_target_cm": round(capacity.seating_target_cm(prefs)),
        "candidate_categories": archetypes.candidate_categories(prefs),
        "available_categories": sorted(summary.keys()),
        "category_summary": summary,
        "placed_categories": sorted({p.category for _i, p in placed}),
        "quantity_caps": archetypes.caps_for(analysis.area_cm2 / 10_000.0),
    }


def _coerce_plan(data: dict, summary: dict, analysis: RoomAnalysis) -> LayoutPlan:
    """Turn raw (schema-valid) LLM JSON into a trusted LayoutPlan: drop unknown/
    unavailable categories, clamp quantities to area caps, dedupe, pin essentials.
    Deliberately does NOT override the LLM's room-aware counts."""
    raw_items = data.get("items", []) if isinstance(data, dict) else []
    caps = archetypes.caps_for(analysis.area_cm2 / 10_000.0)
    by_cat: dict[str, PlanItem] = {}
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        cat = it.get("category")
        if cat not in _VALID_CATEGORIES or cat not in summary:
            continue  # off-vocab, or category absent from the catalog -> drop
        try:
            qty = int(it.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 1
        qty = max(1, min(qty, caps.get(cat, 1)))
        tier = it.get("tier")
        tier = tier if tier in _VALID_TIERS else "essential"
        if cat in ESSENTIAL_CATEGORIES:
            tier = "essential"  # domain truth, not a room-size call
        try:
            priority = int(it.get("priority", archetypes.order_index(cat)))
        except (TypeError, ValueError):
            priority = archetypes.order_index(cat)
        priority = max(0, min(priority, 99))
        if cat in by_cat:  # merge duplicate categories (keep the larger count)
            by_cat[cat].quantity = max(by_cat[cat].quantity, qty)
            continue
        by_cat[cat] = PlanItem(category=cat, quantity=qty, tier=tier, priority=priority)

    _ensure_essentials(by_cat, summary)
    items = sorted(by_cat.values(), key=lambda i: archetypes.order_index(i.category))
    return LayoutPlan(
        archetype=str(data.get("archetype", "")),
        items=items,
        rationale=str(data.get("rationale", "")),
    )


SEATS_PER_SOFA = 3  # prompt-taught rule (see archetypes / memory): one sofa seats ~3


def _seating_note(plan: LayoutPlan, prefs: Preferences) -> str | None:
    """If the user asked for more seats than the room can hold at proper clearances,
    explain the shortfall. The plan is already clamped to area caps, so its sofa+chair
    count is what actually fits; we surface that instead of silently under-delivering."""
    requested = prefs.seating_capacity
    if not requested:
        return None
    planned = sum(
        (SEATS_PER_SOFA if it.category == "sofa" else 1) * it.quantity
        for it in plan.items
        if it.category in ("sofa", "accent_chair")
    )
    if planned >= requested:
        return None
    return (
        f"This room comfortably seats about {planned}. To seat {requested} you'd need a "
        f"larger room - the layout is built for the {planned} that fit with clear walkways."
    )


def _ensure_essentials(by_cat: dict[str, PlanItem], summary: dict) -> None:
    """Guarantee a family room always has its essentials (if the catalog has them),
    even if the LLM omitted one - includes the >=1 sofa guarantee."""
    for cat in ESSENTIAL_CATEGORIES:
        if cat not in by_cat and cat in summary:
            by_cat[cat] = PlanItem(
                category=cat, quantity=1, tier="essential",
                priority=archetypes.order_index(cat),
            )


async def get_plan(room: Room, prefs: Preferences, placed=None) -> tuple[LayoutPlan, str]:
    """Returns (plan, source='llm'). Cached by (room_hash, prefs_hash).

    Raises AppError(PLAN_UNAVAILABLE) if the LLM is unavailable or returns nothing
    usable - there is no second path.
    """
    placed = placed or []
    analysis = analyze_room(room)
    key = f"{analysis.analysis_hash}:{_prefs_hash(prefs)}"
    cached = _plan_cache.get(key)
    if cached is not None:
        return cached

    repo = get_repository()
    summary = repo.category_summary(prefs)
    facts = _facts(room, prefs, analysis, summary, placed)

    data = await copy_service._llm_generate("layout_plan", facts, copy_service.INSTRUCTIONS["layout_plan"])
    if data is None:
        raise AppError(
            PLAN_UNAVAILABLE,
            "Layout planning is unavailable right now - the design engine could not be reached.",
            status_code=503,
        )
    try:
        plan = _coerce_plan(data, summary, analysis)
    except Exception as exc:  # noqa: BLE001 - a malformed plan is a planning failure, not a 500
        logger.warning("Plan coercion failed: %s", exc, exc_info=True)
        raise AppError(PLAN_UNAVAILABLE, "Layout planning produced an invalid result.", status_code=503) from exc
    if not plan.items:
        raise AppError(PLAN_UNAVAILABLE, "Layout planning produced an empty result.", status_code=503)

    plan.seating_note = _seating_note(plan, prefs)

    result = (plan, "llm")
    _plan_cache.put(key, result)
    return result


def clear_cache() -> None:
    _plan_cache.clear()
