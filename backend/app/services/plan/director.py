"""The LLM Layout Director: preferences + room facts -> a LayoutPlan.

The LLM decides ONLY which categories belong, how many of each, and a closed-vocab
arrangement anchor per category - never coordinates, never products (it sees only a
per-category summary). Output is schema-constrained, validated, clamped, and cached by
(room_hash + prefs_hash). Any failure falls back to a deterministic heuristic plan, so
the feature works with no OpenAI key.
"""

import hashlib
import json
import logging
from typing import get_args

from app.models.geometry import Room
from app.models.plan import Anchor, AnchorRef, LayoutPlan, PlanItem
from app.models.preferences import Preferences
from app.models.products import Category
from app.services.ai import copy_service
from app.services.catalog import get_repository
from app.services.plan import archetypes, capacity
from app.services.spatial.analyze import analyze_room
from app.services.spatial.cache import LRUCache
from app.services.spatial.core import RoomAnalysis

logger = logging.getLogger("zory.plan")

_VALID_ANCHORS = set(get_args(Anchor))
_VALID_REFS = set(get_args(AnchorRef))
_VALID_CATEGORIES = set(get_args(Category)) - {"custom"}

_plan_cache: LRUCache[tuple[LayoutPlan, str]] = LRUCache(128)


def _prefs_hash(prefs: Preferences) -> str:
    raw = json.dumps(prefs.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _facts(room: Room, prefs: Preferences, analysis: RoomAnalysis, summary: dict, placed) -> dict:
    minx, miny, maxx, maxy = analysis.polygon.bounds
    return {
        "room_area_m2": round(analysis.area_cm2 / 10_000.0, 1),
        "room_w_cm": round(maxx - minx),
        "room_d_cm": round(maxy - miny),
        "has_focal_wall": analysis.focal_wall_index is not None,
        "windows": len(room.windows),
        "doors": len(room.doors),
        "styles": list(prefs.styles),
        "colors": list(prefs.colors),
        "room_purpose": prefs.room_purpose,
        "seating_capacity": capacity.target_capacity(prefs),
        "seating_target_cm": round(capacity.seating_target_cm(prefs)),
        "candidate_categories": archetypes.candidate_categories(prefs),
        "available_categories": sorted(summary.keys()),
        "category_summary": summary,
        "placed_categories": sorted({p.category for _i, p in placed}),
        "quantity_caps": archetypes.caps_for(analysis.area_cm2 / 10_000.0),
    }


def _resolve_anchor(category: str, anchor, ref, analysis: RoomAnalysis) -> tuple[str, str]:
    """Snap to valid tokens and demote anchors whose geometry is unavailable."""
    default_a, default_r = archetypes.DEFAULT_ANCHORS.get(category, ("center", "room"))
    anchor = anchor if anchor in _VALID_ANCHORS else default_a
    ref = ref if ref in _VALID_REFS else default_r
    if ref == "focal_wall" and analysis.focal_wall_index is None:
        anchor, ref = "center", "room"
    if ref == "window" and not analysis.window_strips:
        anchor, ref = "center", "room"
    return anchor, ref


def _coerce_plan(data: dict, summary: dict, analysis: RoomAnalysis) -> LayoutPlan:
    raw_items = data.get("items", []) if isinstance(data, dict) else []
    caps = archetypes.caps_for(analysis.area_cm2 / 10_000.0)
    by_cat: dict[str, PlanItem] = {}
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        cat = it.get("category")
        if cat not in _VALID_CATEGORIES or cat not in summary:
            continue  # category absent from catalog -> drop
        anchor, ref = _resolve_anchor(cat, it.get("anchor"), it.get("anchor_ref"), analysis)
        try:
            qty = int(it.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 1
        qty = max(1, min(qty, caps.get(cat, 1)))
        if cat in by_cat:  # merge duplicate categories
            by_cat[cat].quantity = max(by_cat[cat].quantity, qty)
            continue
        by_cat[cat] = PlanItem(
            category=cat, quantity=qty, anchor=anchor, anchor_ref=ref,
            priority=archetypes.order_index(cat),
        )
    items = _prune_refs(sorted(by_cat.values(), key=lambda i: archetypes.order_index(i.category)))
    return LayoutPlan(
        archetype=str(data.get("archetype", "")),
        items=items,
        rationale=str(data.get("rationale", "")),
    )


def _prune_refs(items: list[PlanItem]) -> list[PlanItem]:
    """If an item anchors to a category absent from the plan, fall back to room."""
    present = {i.category for i in items}
    for item in items:
        if item.anchor_ref in {"sofa", "tv_unit"} and item.anchor_ref not in present:
            item.anchor_ref = "room"
    return items


def fallback_plan(prefs: Preferences, analysis: RoomAnalysis, summary: dict) -> LayoutPlan:
    """Deterministic heuristic plan (no LLM): purpose + style + capacity driven."""
    cats = [c for c in archetypes.candidate_categories(prefs) if c in summary]
    chairs = capacity.extra_seats_as_chairs(prefs)
    area_m2 = analysis.area_cm2 / 10_000.0
    caps = archetypes.caps_for(area_m2)
    big, huge = area_m2 >= 35.0, area_m2 >= 60.0
    items: list[PlanItem] = []
    for cat in cats:
        anchor, ref = _resolve_anchor(cat, *archetypes.DEFAULT_ANCHORS.get(cat, ("center", "room")), analysis)
        if cat == "accent_chair":
            qty = max(chairs, 2 if big else 1, 1)
        elif cat == "side_table":
            qty = 2 if area_m2 >= 12.0 else 1
        elif cat == "lighting":
            qty = 3 if huge else 2 if big else 1
        elif cat == "decor":
            qty = 4 if huge else 3 if big else 2 if area_m2 >= 12.0 else 1
        elif cat == "storage":
            qty = 2 if huge else 1
        else:
            qty = 1
        qty = max(1, min(qty, caps.get(cat, 1)))
        items.append(PlanItem(
            category=cat, quantity=qty, anchor=anchor, anchor_ref=ref,
            priority=archetypes.order_index(cat),
        ))
    items = _prune_refs(sorted(items, key=lambda i: archetypes.order_index(i.category)))
    return LayoutPlan(
        archetype=archetypes.archetype_name(prefs),
        items=items,
        rationale="Chosen from your room purpose, style and seating needs.",
    )


async def get_plan(room: Room, prefs: Preferences, placed=None) -> tuple[LayoutPlan, str]:
    """Returns (plan, source) where source is 'llm' or 'template'. Cached + fallback-safe."""
    placed = placed or []
    analysis = analyze_room(room)
    key = f"{analysis.analysis_hash}:{_prefs_hash(prefs)}"
    cached = _plan_cache.get(key)
    if cached is not None:
        return cached

    repo = get_repository()
    summary = repo.category_summary(prefs)
    facts = _facts(room, prefs, analysis, summary, placed)

    plan: LayoutPlan
    source: str
    data = await copy_service._llm_generate("layout_plan", facts, copy_service.INSTRUCTIONS["layout_plan"])
    if data is not None:
        try:
            plan = _coerce_plan(data, summary, analysis)
            source = "llm"
            if not plan.items:
                plan, source = fallback_plan(prefs, analysis, summary), "template"
        except Exception:  # noqa: BLE001 - never fail the request on a bad plan
            logger.warning("Plan coercion failed; using heuristic fallback", exc_info=True)
            plan, source = fallback_plan(prefs, analysis, summary), "template"
    else:
        plan, source = fallback_plan(prefs, analysis, summary), "template"

    result = (plan, source)
    _plan_cache.put(key, result)
    return result


def clear_cache() -> None:
    _plan_cache.clear()
