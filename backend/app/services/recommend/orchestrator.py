"""Whole-room auto-planner for the "Assist with AI" feature.

Composes the EXISTING deterministic spatial + recommendation engine to propose a
complete furniture layout in a single pass. Critically, no LLM or image model is
involved in choosing coordinates:

  * products are chosen by recommend.selector.select_slots (deterministic scoring)
  * poses are chosen by the spatial engine (suggest_pose -> settle -> autofix)
  * every placement is checked by spatial.validate.validate_item before it is kept

The rationale strings are template text built from machine-checked facts, not an
LLM. (An LLM may later phrase nicer copy, but never the geometry.)

Two flows share one response builder:
  * living_room - one best product per category (the original behaviour, unchanged)
  * majlis      - benches lined along the perimeter walls until a seating-capacity
                  target is met, then a centred rug + low table, then accents.
"""

import hashlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count

from app.config import get_settings
from app.models.api import (
    AssistLayoutResponse,
    AssistPlacement,
    AssistSkip,
    AssistTotals,
)
from app.models.geometry import PlacedItem, Pose, Room
from app.models.preferences import Preferences
from app.models.products import CATEGORY_LABELS
from app.models.validation import MUST_FIX_CODES, Finding
from app.routers._common import PlacedProduct, resolve_placed, wall_label
from app.services.catalog import CatalogRepository, get_repository
from app.services.guide.flow import sequence_for_room_type
from app.services.recommend.selector import Candidate, select_slots
from app.services.spatial.analyze import analyze_room
from app.services.spatial.autofix import find_autofix, settle_pose, suggest_pose
from app.services.spatial.core import RoomAnalysis, ZoneData
from app.services.spatial.validate import validate_item
from app.services.recipe.equivalence import compare_layouts
from app.services.recipe.models import CountRule, Recipe, RoleDefinition
from app.services.recipe.predicates import resolve_predicate
from app.services.recipe.registry import get_recipe
from app.services.recipe.strategies import resolve_strategy
from app.services.spatial.zones import (
    CategoryStats,
    R_MAJLIS_PERIMETER_SEATING,
    anchor_pose,
    secondary_nook_zones,
    zones_for_category,
)

logger = logging.getLogger("zory")

# Proposed items get deterministic, recognisable ids; the front-end re-mints real
# ids when the user accepts so accepted items never collide with existing ones.
AUTO_PREFIX = "auto-"


class RecipeError(RuntimeError):
    """Raised when the recipe-driven planner cannot run (e.g. no recipe registered)."""


def _default_seat_target(analysis: RoomAnalysis) -> int:
    """Sensible Majlis seating target from room area when none is supplied."""
    area_m2 = analysis.area_cm2 / 10_000.0
    if area_m2 < 16.0:
        return 6  # small
    if area_m2 < 28.0:
        return 8  # medium
    return 11  # large


def _rationale(category: str, zone: ZoneData, analysis: RoomAnalysis) -> str:
    """Deterministic, template-only explanation (no LLM) from the chosen zone."""
    label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
    if R_MAJLIS_PERIMETER_SEATING in zone.reason_codes:
        side = wall_label(analysis.walls[zone.wall_index]) if zone.wall_index is not None else "a"
        where = f"the {side} wall" if side in ("top", "bottom", "left", "right") else "a wall"
        return f"{label} lined along {where} as majlis perimeter seating, keeping the centre open."
    if zone.kind == "wall_band" and zone.wall_index is not None:
        side = wall_label(analysis.walls[zone.wall_index])
        if side in ("top", "bottom", "left", "right"):
            return f"{label} placed along the {side} wall, keeping doorways and walkways clear."
        return f"{label} placed against a wall, keeping doorways and walkways clear."
    return f"{label} positioned to complement the seating while keeping the room open to move through."


def _commit(
    category: str,
    candidate: Candidate,
    pose: Pose,
    zone_id: str | None,
    instance_id: str,
    analysis: RoomAnalysis,
    working: list[PlacedProduct],
) -> tuple[AssistPlacement | None, PlacedItem | None, str | None]:
    """Validate (+ autofix) one candidate pose; return a placement or a skip reason.

    Never emits an item with an unresolved hard error (door swing / overlap / OOB /
    blocked walkway): if autofix can't clear it, the caller skips the item.
    """
    product = candidate.product
    item = PlacedItem(
        instance_id=instance_id, product_id=product.id,
        x=pose.x, y=pose.y, rotation_deg=pose.rotation_deg, zone_id=zone_id,
    )
    findings = validate_item(analysis, working, item, product)
    if any(f.code in MUST_FIX_CODES for f in findings):
        fix = find_autofix(analysis, working, item, product, findings)
        if fix is not None:
            item = item.model_copy(
                update={"x": fix.pose.x, "y": fix.pose.y, "rotation_deg": fix.pose.rotation_deg}
            )
            findings = validate_item(analysis, working, item, product)

    hard = [f for f in findings if f.code in MUST_FIX_CODES]
    if hard:
        return None, None, hard[0].code

    placement = AssistPlacement(
        instance_id=instance_id, product_id=product.id, product=product, category=category,
        pose=Pose(x=item.x, y=item.y, rotation_deg=item.rotation_deg),
        zone_id=zone_id, slot="best_match", fit_facts=candidate.facts,
        reason_codes=candidate.zone.reason_codes,
        rationale=_rationale(category, candidate.zone, analysis), notices=candidate.notices,
    )
    return placement, item, None


def _place_majlis_seating(
    analysis: RoomAnalysis,
    prefs: Preferences,
    repo,
    stats,
    working: list[PlacedProduct],
    placements: list[AssistPlacement],
    ids,
    target: int,
) -> bool:
    """Line benches along the perimeter walls until the seating target is reached.

    One bench per wall (longest clear wall first), so seating spreads across 2-3
    walls and the centre stays open. Re-derives zones each round so later benches
    account for the ones already placed. Returns True if any bench was placed.
    """
    used_walls: set[int] = set()
    seated = sum(p.seating_capacity for _i, p in working if p.seating_capacity > 0)
    placed_any = False

    while seated < target:
        zones = zones_for_category("sofa", analysis, working, stats, room_type="majlis")
        zone = next((z for z in zones if z.wall_index not in used_walls), None)
        if zone is None:
            break  # no more unused perimeter walls
        used_walls.add(zone.wall_index)  # one bench per wall segment - no duplicates

        # pick the best Majlis bench that fits THIS wall band
        result = select_slots("sofa", [zone], prefs, working, repo)
        candidate = result.best
        if candidate is None:
            continue
        product = candidate.product
        pose = settle_pose(analysis, working, product, anchor_pose(zone, product, analysis))
        placement, item, _reason = _commit(
            "sofa", candidate, pose, zone.id, f"{AUTO_PREFIX}{next(ids)}", analysis, working
        )
        if placement is None:
            continue
        placements.append(placement)
        working.append((item, product))
        seated += product.seating_capacity
        placed_any = True

    return placed_any


def _proposal_id(analysis: RoomAnalysis, placements: list[AssistPlacement]) -> str:
    """Stable id so identical inputs yield an identical proposal id (no clock/rng)."""
    h = hashlib.sha256()
    h.update(analysis.analysis_hash.encode())
    for p in placements:
        h.update(f"{p.product_id}:{p.pose.x}:{p.pose.y}:{p.pose.rotation_deg};".encode())
    return "lay_" + h.hexdigest()[:10]


def _finalize_response(
    analysis: RoomAnalysis,
    placements: list[AssistPlacement],
    skipped: list[AssistSkip],
    working: list[PlacedProduct],
) -> AssistLayoutResponse:
    """Build the response (advisory findings + totals + proposal id) from a planned
    layout. Shared by both planner paths so finalization is identical by construction;
    this isolates any legacy/recipe divergence to the placement loop alone."""
    # Advisory (non-blocking) findings on the proposed items, validated against the
    # final full layout - mirrors /summary's layout_findings so the UI can surface
    # window / clearance warnings without blocking acceptance.
    findings_out: list[Finding] = []
    for item, product in working:
        if not item.instance_id.startswith(AUTO_PREFIX):
            continue
        others = [pp for pp in working if pp[0].instance_id != item.instance_id]
        for finding in validate_item(analysis, others, item, product):
            if finding.severity in ("warning", "error"):
                findings_out.append(finding)

    total_price = sum(
        product.price for item, product in working if item.instance_id.startswith(AUTO_PREFIX)
    )

    return AssistLayoutResponse(
        proposal_id=_proposal_id(analysis, placements),
        placements=placements,
        skipped=skipped,
        findings=findings_out,
        totals=AssistTotals(
            item_count=len(placements),
            total_price=total_price,
            currency=get_settings().base_currency,
        ),
    )


def plan_layout(
    room: Room,
    preferences: Preferences,
    placed_items: list[PlacedItem],
    categories: list[str] | None = None,
    room_type: str | None = "living_room",
) -> AssistLayoutResponse:
    analysis = analyze_room(room)  # cached by room hash; reused for every category
    repo = get_repository()
    stats = repo.category_stats()

    # Reconcile the room type from preferences (Phase 2 field) and the request param,
    # and make sure the selector/scoring see it too (only inject for non-living_room
    # so the living-room flow stays byte-identical).
    effective_room_type = preferences.room_type or room_type or "living_room"
    if effective_room_type != "living_room" and preferences.room_type is None:
        preferences = preferences.model_copy(update={"room_type": effective_room_type})

    # Working layout, seeded with whatever the user already placed/kept. Each new
    # placement is appended so later categories see (and avoid) earlier ones.
    working: list[PlacedProduct] = resolve_placed(placed_items)
    have_categories = {product.category for _i, product in working}

    sequence = categories if categories is not None else sequence_for_room_type(effective_room_type)

    placements: list[AssistPlacement] = []
    skipped: list[AssistSkip] = []
    ids = count(1)

    for category in sequence:
        # Majlis seating: place MULTIPLE benches along the perimeter (always tops up
        # toward the capacity target, even if the user already placed some seating).
        if effective_room_type == "majlis" and category == "sofa":
            target = preferences.seating_capacity or _default_seat_target(analysis)
            if not _place_majlis_seating(analysis, preferences, repo, stats, working, placements, ids, target):
                skipped.append(AssistSkip(category="sofa", reason="NO_FIT"))
            have_categories.add("sofa")
            continue

        # Respect the user's own items: don't add a second essential they placed.
        if category in have_categories:
            skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
            continue

        zones = zones_for_category(category, analysis, working, stats, room_type=effective_room_type)
        result = select_slots(category, zones, preferences, working, repo)
        candidate = result.best
        if candidate is None:
            skipped.append(
                AssistSkip(category=category, reason=str(result.no_fit_hints.get("reason", "NO_FIT")))
            )
            continue

        # Deterministic pose from the existing spatial engine, anchored to the zone
        # the selector chose (room_type threaded so Majlis centres rug/table).
        pose, zone_id, _alts = suggest_pose(
            analysis, working, candidate.product, stats, candidate.zone.id, room_type=effective_room_type
        )
        placement, item, reason = _commit(
            category, candidate, pose, zone_id, f"{AUTO_PREFIX}{next(ids)}", analysis, working
        )
        if placement is None:
            # Could not place without blocking a door / overlapping / leaving the room.
            skipped.append(AssistSkip(category=category, reason=reason or "NO_VALID_SPOT"))
            continue

        placements.append(placement)
        working.append((item, candidate.product))
        have_categories.add(category)

    return _finalize_response(analysis, placements, skipped, working)


# ============================================================================
# Recipe interpreter (Phase 3)
#
# The interpreter is the recipe-driven source of orchestration logic. It reads
# WHAT to place from the recipe (roles, count rules, dependency graph), gets WHERE
# from strategies (via the registry), computes poses with the existing placement
# helpers, and proves correctness with the unchanged gate (_commit -> validate_item).
# It reproduces the legacy planner's output for the shipped recipes (equivalence is
# enforced by tests + shadow mode). The legacy plan_layout + _place_majlis_seating
# are left untouched as the equivalence reference.
# ============================================================================


@dataclass
class _PlanState:
    """Mutable interpreter context threaded through role execution."""

    analysis: RoomAnalysis
    preferences: Preferences
    repo: CatalogRepository
    stats: CategoryStats
    room_type: str
    working: list[PlacedProduct]
    placements: list[AssistPlacement] = field(default_factory=list)
    skipped: list[AssistSkip] = field(default_factory=list)
    have_categories: set[str] = field(default_factory=set)
    ids: Iterator[int] = field(default_factory=lambda: count(1))
    # role -> a pinned zone (template generation forces the primary piece onto a chosen
    # wall; every other role still resolves normally and cascades around it)
    zone_overrides: dict[str, ZoneData] = field(default_factory=dict)


def _topological_order(roles: list[RoleDefinition]) -> list[RoleDefinition]:
    """Resolve roles in dependency order (depends_on), STABLE on declared order.

    Stability matters: the declared recipe order is already a valid topological order
    for the shipped recipes, so the linearisation equals the declared order and output
    is unchanged. If a recipe ever lists a dependent before its anchor, this still
    places the anchor first. Raises on a cyclic / unsatisfiable graph.
    """
    declared = {role.role: i for i, role in enumerate(roles)}
    done: set[str] = set()
    remaining = list(roles)
    ordered: list[RoleDefinition] = []
    while remaining:
        ready = [r for r in remaining if all(dep in done for dep in r.depends_on)]
        if not ready:
            raise RecipeError(f"recipe has cyclic/unsatisfiable dependencies among {[r.role for r in remaining]}")
        nxt = min(ready, key=lambda r: declared[r.role])  # declared-order tie-break
        ordered.append(nxt)
        done.add(nxt.role)
        remaining.remove(nxt)
    return ordered


def _resolve_recipe_predicates(recipe: Recipe) -> None:
    """Predicate awareness: resolve every predicate reference up-front. This is an
    orchestration decision - the interpreter refuses to run a recipe whose intent it
    cannot resolve - but it does NOT enforce predicates. The validation gate
    (_commit -> validate_item) remains the sole, unchanged authority on correctness."""
    for role in recipe.roles:
        for predicate in role.predicates:
            resolve_predicate(predicate.name)  # raises on unknown


def _run_strategy(role: RoleDefinition, category: str, st: _PlanState) -> list[ZoneData]:
    """Invoke the role's zone strategy through the registry (Phase 1 strategies still
    delegate to the existing zone code, so zones are identical to the legacy path)."""
    strategy = resolve_strategy(role.zone_strategy.name)
    return strategy.resolver(category, st.room_type, st.analysis, st.working, st.stats, role.zone_strategy.params)


def _metric_of(product, metric: str) -> int:
    return int(getattr(product, metric, 0) or 0)


def _unit_key(zone: ZoneData, one_per: str | None):
    """Granularity key for until_target: 'wall_segment' -> one item per wall."""
    if one_per == "wall_segment":
        return zone.wall_index
    return zone.id


def _count_target(rule: CountRule, st: _PlanState) -> int:
    if rule.source == "pref_or_area_default":
        return st.preferences.seating_capacity or _default_seat_target(st.analysis)
    if rule.max is not None:
        return rule.max
    raise RecipeError(f"until_target count rule needs a resolvable target (source={rule.source!r})")


def _execute_single(role: RoleDefinition, st: _PlanState) -> None:
    category = role.categories[0]
    if category in st.have_categories:
        st.skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
        return

    pinned = st.zone_overrides.get(role.role)
    zones = [pinned] if pinned is not None else _run_strategy(role, category, st)
    result = select_slots(category, zones, st.preferences, st.working, st.repo)
    candidate = result.best
    if candidate is None:
        st.skipped.append(AssistSkip(category=category, reason=str(result.no_fit_hints.get("reason", "NO_FIT"))))
        return

    # Strategy-based pose generation (Phase 5): anchor directly to the candidate zone the
    # strategy produced and settle it - NO zones_for_category re-derivation. Equivalent to
    # suggest_pose because the strategy zones are byte-identical to the legacy dispatch
    # (Phase 4), so suggest_pose's zone-by-id lookup would resolve to this very zone.
    pose = settle_pose(
        st.analysis, st.working, candidate.product, anchor_pose(candidate.zone, candidate.product, st.analysis)
    )
    placement, item, reason = _commit(
        category, candidate, pose, candidate.zone.id, f"{AUTO_PREFIX}{next(st.ids)}", st.analysis, st.working
    )
    if placement is None:
        st.skipped.append(AssistSkip(category=category, reason=reason or "NO_VALID_SPOT"))
        return

    st.placements.append(placement)
    st.working.append((item, candidate.product))
    st.have_categories.add(category)


def _execute_until_target(role: RoleDefinition, st: _PlanState) -> None:
    """Generic multi-instance placement toward a metric target (e.g. seating capacity),
    one item per `one_per` unit. This is the recipe-driven generalisation of the legacy
    Majlis perimeter-seating loop - no hardcoded room_type/category."""
    category = role.categories[0]
    rule = role.count
    metric = rule.metric or "seating_capacity"
    target = _count_target(rule, st)

    used: set = set()
    seated = sum(_metric_of(p, metric) for _i, p in st.working if _metric_of(p, metric) > 0)
    placed_any = False

    while seated < target:
        zones = _run_strategy(role, category, st)
        zone = next((z for z in zones if _unit_key(z, rule.one_per) not in used), None)
        if zone is None:
            break  # no more units (e.g. perimeter walls) available
        used.add(_unit_key(zone, rule.one_per))

        result = select_slots(category, [zone], st.preferences, st.working, st.repo)
        candidate = result.best
        if candidate is None:
            continue
        product = candidate.product
        pose = settle_pose(st.analysis, st.working, product, anchor_pose(zone, product, st.analysis))
        placement, item, _reason = _commit(
            category, candidate, pose, zone.id, f"{AUTO_PREFIX}{next(st.ids)}", st.analysis, st.working
        )
        if placement is None:
            continue
        st.placements.append(placement)
        st.working.append((item, product))
        seated += _metric_of(product, metric)
        placed_any = True

    if not placed_any:
        st.skipped.append(AssistSkip(category=category, reason="NO_FIT"))
    st.have_categories.add(category)


def _execute_mirror_pair(role: RoleDefinition, st: _PlanState) -> None:
    """Place one item per side zone the strategy produced (left + right), each gated.

    Used for bedroom nightstands: 2 when both sides of the bed are clear, 1 when only
    one fits, 0 (skip) when neither does. The strategy already carves out door/window
    keep-out, and the gate validates every placement - so this never blocks a door.
    """
    category = role.categories[0]
    if category in st.have_categories:
        st.skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
        return

    zones = _run_strategy(role, category, st)  # up to two side zones (left, right)
    placed_any = False
    for zone in zones[: (role.count.max or 2)]:
        result = select_slots(category, [zone], st.preferences, st.working, st.repo)
        candidate = result.best
        if candidate is None:
            continue
        product = candidate.product
        pose = settle_pose(st.analysis, st.working, product, anchor_pose(zone, product, st.analysis))
        placement, item, _reason = _commit(
            category, candidate, pose, zone.id, f"{AUTO_PREFIX}{next(st.ids)}", st.analysis, st.working
        )
        if placement is None:
            continue
        st.placements.append(placement)
        st.working.append((item, product))
        placed_any = True

    if not placed_any:
        st.skipped.append(AssistSkip(category=category, reason="NO_FIT"))
    st.have_categories.add(category)


def _execute_fill_available(role: RoleDefinition, st: _PlanState) -> None:
    """Fill the available zones with a count that scales with room area.

    Used for accent pieces (extra lamps, decor, side tables, accent chairs): a bigger
    room places more, a small room places one. Bounded by both the area cap
    (per_area_m2) and the number of zones the strategy produced, and by role.count.max.
    Each placement is gated, so it never blocks a door or overflows the room.
    """
    category = role.categories[0]
    if category in st.have_categories:
        st.skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
        return

    zones = _run_strategy(role, category, st)
    area_m2 = st.analysis.area_cm2 / 10_000.0
    per = role.count.per_area_m2 or 12.0
    cap = max(1, round(area_m2 / per))
    if role.count.max is not None:
        cap = min(cap, role.count.max)

    placed = 0
    for zone in zones:
        if placed >= cap:
            break
        result = select_slots(category, [zone], st.preferences, st.working, st.repo)
        candidate = result.best
        if candidate is None:
            continue
        product = candidate.product
        pose = settle_pose(st.analysis, st.working, product, anchor_pose(zone, product, st.analysis))
        placement, item, _reason = _commit(
            category, candidate, pose, zone.id, f"{AUTO_PREFIX}{next(st.ids)}", st.analysis, st.working
        )
        if placement is None:
            continue
        st.placements.append(placement)
        st.working.append((item, product))
        placed += 1

    if placed == 0:
        st.skipped.append(AssistSkip(category=category, reason="NO_FIT"))
    st.have_categories.add(category)


def _furnish_secondary_zone(st: _PlanState) -> None:
    """Composition pass: in a LARGE room, furnish secondary cluster(s) in the open area.

    The recipe builds one seating group; on a big floor that leaves obvious empty
    regions. This lays out coherent reading/conversation nooks there (a side table, one
    or two accent chairs facing the primary group, a floor lamp) so the room reads as
    composed rather than sparse. The number of nooks scales with floor area - a great
    room gets two or three, each filling the next-largest open region - so very large
    rooms don't end up with a tiny group lost in empty space. A no-op for normal rooms
    (the geometry returns nothing below the size threshold), so smaller rooms and the
    goldens are unaffected. Every piece still passes the validation gate.
    """
    # one nook for a large room, at most two for a great-room - more than that reads as a
    # cluttered pile of identical chairs rather than composed zones.
    max_zones = min(2, max(1, int(st.analysis.area_cm2 / 320_000.0)))
    for _ in range(max_zones):
        zones = secondary_nook_zones(st.analysis, st.working, st.stats)
        if not zones:
            break  # no open region large enough remains - stop filling
        placed_any = False
        for zone in zones:
            category = zone.category
            result = select_slots(category, [zone], st.preferences, st.working, st.repo)
            candidate = result.best
            if candidate is None:
                continue
            product = candidate.product
            # pose is taken from the composed nook center (not a wall anchor), then settled
            base = Pose(x=zone.origin[0], y=zone.origin[1], rotation_deg=zone.rotation_deg)
            pose = settle_pose(st.analysis, st.working, product, base)
            placement, item, _reason = _commit(
                category, candidate, pose, zone.id, f"{AUTO_PREFIX}{next(st.ids)}", st.analysis, st.working
            )
            if placement is None:
                continue
            st.placements.append(placement)
            st.working.append((item, product))
            placed_any = True
        if not placed_any:
            break  # couldn't place anything in the remaining region - avoid looping


def _execute_role(role: RoleDefinition, st: _PlanState) -> None:
    mode = role.count.mode
    if mode == "single":
        _execute_single(role, st)
    elif mode == "until_target":
        _execute_until_target(role, st)
    elif mode == "mirror_pair":
        _execute_mirror_pair(role, st)
    elif mode == "fill_available":
        _execute_fill_available(role, st)
    else:
        # per_anchor is part of the count vocabulary but no shipped recipe uses it yet.
        raise RecipeError(f"count mode '{mode}' is not implemented yet (role '{role.role}')")


def plan_layout_from_recipe(
    room: Room,
    preferences: Preferences,
    placed_items: list[PlacedItem],
    room_type: str | None = "living_room",
    zone_overrides: dict[str, ZoneData] | None = None,
) -> AssistLayoutResponse:
    """Recipe interpreter entry point (Phase 3).

    Drives orchestration from the recipe: dependency-ordered roles, strategy-registry
    zone generation, generic count-rule execution. Same engine + gate as plan_layout;
    output is equivalent for the shipped recipes (proven by tests + shadow mode). Does
    NOT handle a `categories` override - the dispatcher routes those to legacy. Raises
    RecipeError if no recipe is registered.
    """
    effective_room_type = preferences.room_type or room_type or "living_room"
    recipe = get_recipe(effective_room_type)
    if recipe is None:
        raise RecipeError(f"No recipe registered for room_type '{effective_room_type}'")
    _resolve_recipe_predicates(recipe)  # predicate awareness: refuse unresolvable intent

    analysis = analyze_room(room)
    repo = get_repository()
    if effective_room_type != "living_room" and preferences.room_type is None:
        preferences = preferences.model_copy(update={"room_type": effective_room_type})

    working: list[PlacedProduct] = resolve_placed(placed_items)
    st = _PlanState(
        analysis=analysis,
        preferences=preferences,
        repo=repo,
        stats=repo.category_stats(),
        room_type=effective_room_type,
        working=working,
        have_categories={product.category for _i, product in working},
        zone_overrides=zone_overrides or {},
    )

    for role in _topological_order(recipe.roles):
        _execute_role(role, st)

    # composition layer: opted-in recipes get a secondary cluster in a large room's
    # leftover open area (majlis opts out - it composes itself via perimeter seating)
    if recipe.compose_secondary:
        _furnish_secondary_zone(st)

    return _finalize_response(st.analysis, st.placements, st.skipped, st.working)


def _primary_role(recipe: Recipe) -> RoleDefinition | None:
    """The single 'anchor' piece a room is built around (sofa, bed) - the one whose wall
    we vary to make templates. None for recipes with no single focal piece (majlis)."""
    for role in recipe.roles:
        if role.essential and role.zone_strategy.name == "focal_wall" and role.count.mode == "single":
            return role
    return None


def _wall_side(analysis: RoomAnalysis, zone: ZoneData) -> str:
    """Which side of the room a zone's wall is on, as the user sees it on the canvas.

    Uses the wall's outward normal (unique per wall) rather than the zone centroid - a
    door can push the clear band to one side and skew a centroid-based guess.
    """
    if zone.wall_index is not None and zone.wall_index < len(analysis.walls):
        n = analysis.walls[zone.wall_index].normal  # points INTO the room
        ox, oy = -n[0], -n[1]  # so the wall is on the OUTWARD side
    else:
        c = zone.polygon.centroid
        rc = analysis.polygon.centroid
        ox, oy = c.x - rc.x, c.y - rc.y
    if abs(ox) >= abs(oy):
        return "right" if ox > 0 else "left"
    return "bottom" if oy > 0 else "top"  # canvas y grows downward


def _anchor_label(analysis: RoomAnalysis, room: Room, zone: ZoneData, piece: str) -> tuple[str, str]:
    """A human name for a template, by where its anchor piece sits. Returns (label, side)."""
    side = _wall_side(analysis, zone)
    wi = zone.wall_index
    if wi is not None and any(w.wall_index == wi for w in room.windows):
        return f"{piece} under the window", side
    if wi is not None and wi == analysis.longest_clear_wall_index:
        return f"{piece} on the long wall", side
    return f"{piece} on the {side} wall", side


def _template_layout_score(resp: AssistLayoutResponse) -> float:
    """A design-quality score used to rank/recommend templates. Today it rewards a working
    sofa<->TV pair (the TV actually faces the sofa, at a comfortable distance) - so we
    recommend a sofa wall whose opposite wall can host the TV, instead of one where the TV
    gets pushed to a side wall. 0 for rooms without a sofa+TV (e.g. bedrooms), leaving
    their order unchanged."""
    from app.services.spatial.geometry_utils import front_vector

    by_cat = {p.category: p for p in resp.placements}
    sofa, tv = by_cat.get("sofa"), by_cat.get("tv_unit")
    if sofa is None or tv is None:
        return 0.0
    f = front_vector(sofa.pose.rotation_deg)
    fx = sofa.pose.x + f[0] * sofa.product.depth_cm / 2.0
    fy = sofa.pose.y + f[1] * sofa.product.depth_cm / 2.0
    vx, vy = tv.pose.x - fx, tv.pose.y - fy
    d = (vx * vx + vy * vy) ** 0.5
    facing = (f[0] * vx + f[1] * vy) / d if d > 1.0 else -1.0
    score = 2.0 if facing > 0.6 else (0.7 if facing > 0.3 else 0.0)  # TV in front of the sofa
    if 200.0 <= d <= 430.0:
        score += 1.0  # comfortable viewing distance
    elif d <= 480.0:
        score += 0.4
    return score


def _template_quality_ok(room: Room, zone: ZoneData, category: str) -> bool:
    """Would a designer offer this anchor wall? A bed wants a solid wall (never under a
    window or beside the door); a sofa may sit under a window but not on the door wall.
    Used to avoid surfacing weak alternatives - we only fall back to one if nothing
    better exists."""
    wi = zone.wall_index
    if wi is None:
        return True
    on_door = any(d.wall_index == wi for d in room.doors)
    on_window = any(w.wall_index == wi for w in room.windows)
    if category == "bed":
        return not on_door and not on_window
    return not on_door  # sofa under a window is fine; on the door wall is not


def plan_layout_variants(
    room: Room,
    preferences: Preferences,
    placed_items: list[PlacedItem],
    room_type: str | None = "living_room",
    max_variants: int = 3,
) -> list[tuple[str, AssistLayoutResponse]]:
    """Several complete layouts, made by placing the primary piece on different walls.

    Each template pins the sofa/bed to a candidate wall and re-runs the recipe; the rest
    of the room cascades around it. Curated - distinct walls only, every layout valid (no
    hard errors, primary actually placed), no duplicates, ranked best-first. Falls back to
    a single layout when there's no single focal piece (majlis) or only one workable wall.
    """
    effective_room_type = preferences.room_type or room_type or "living_room"
    recipe = get_recipe(effective_room_type)
    prefs = preferences
    if recipe is not None and effective_room_type != "living_room" and prefs.room_type is None:
        prefs = prefs.model_copy(update={"room_type": effective_room_type})

    primary = _primary_role(recipe) if recipe is not None else None
    if primary is None:  # no single anchor -> one honest layout
        return [("Suggested layout", plan_layout_from_recipe(room, prefs, placed_items, room_type))]

    analysis = analyze_room(room)
    stats = get_repository().category_stats()
    strategy = resolve_strategy(primary.zone_strategy.name)
    cands = strategy.resolver(primary.categories[0], effective_room_type, analysis, [], stats, primary.zone_strategy.params)

    # keep one candidate per distinct wall, best-first
    distinct: list[ZoneData] = []
    seen_walls: set = set()
    for z in cands:
        key = z.wall_index if z.wall_index is not None else id(z)
        if key in seen_walls:
            continue
        seen_walls.add(key)
        distinct.append(z)

    piece = CATEGORY_LABELS.get(primary.categories[0], primary.categories[0].replace("_", " ").title())
    category = primary.categories[0]
    good_rows: list[tuple[str, str, AssistLayoutResponse]] = []  # design-sound options
    other_rows: list[tuple[str, str, AssistLayoutResponse]] = []  # weak fallbacks
    seen_ids: set[str] = set()
    for z in distinct[: max_variants + 3]:  # pool extra so we can drop weak walls
        resp = plan_layout_from_recipe(room, prefs, placed_items, room_type, zone_overrides={primary.role: z})
        if category not in {p.category for p in resp.placements}:
            continue  # primary couldn't be placed on this wall - drop the template
        if any(f.severity == "error" for f in resp.findings):
            continue
        if resp.proposal_id in seen_ids:
            continue  # identical arrangement - not a real alternative
        seen_ids.add(resp.proposal_id)
        label, side = _anchor_label(analysis, room, z, piece)
        bucket = good_rows if _template_quality_ok(room, z, category) else other_rows
        bucket.append((label, side, resp))

    # rank the design-sound options by layout quality (a working sofa<->TV pair wins), so
    # the recommended template is the one that actually composes - stable on the original
    # best-first order for ties (and for bedrooms, which score 0 across the board).
    good_rows.sort(key=lambda r: _template_layout_score(r[2]), reverse=True)
    # only ever surface design-sound options; fall back to the single best weak one only
    # when nothing better exists (e.g. a tiny room with one viable wall)
    rows = good_rows[:max_variants] if good_rows else other_rows[:1]
    if not rows:  # safety net: always return at least the natural layout
        return [(f"{piece} layout", plan_layout_from_recipe(room, prefs, placed_items, room_type))]

    # unique, readable labels (disambiguate collisions by side)
    out: list[tuple[str, AssistLayoutResponse]] = []
    used: set[str] = set()
    for label, side, resp in rows:
        name = label if label not in used else f"{label} ({side})"
        n = 2
        while name in used:
            name = f"{label} ({side}) {n}"
            n += 1
        used.add(name)
        out.append((name, resp))
    return out


def plan_assist_templates(
    room: Room,
    preferences: Preferences,
    placed_items: list[PlacedItem],
    categories: list[str] | None = None,
    room_type: str | None = "living_room",
    max_variants: int = 3,
) -> list[tuple[str, bool, AssistLayoutResponse]]:
    """Mode-aware template set for /assist/layout: (label, recommended, layout).

    Recipe mode + a single-anchor recipe -> several position templates (the first is the
    recommendation). Legacy/shadow/categories-override/no-recipe -> one template, so the
    endpoint always returns the same shape.
    """
    mode = get_settings().assist_planner_mode
    effective_room_type = preferences.room_type or room_type or "living_room"
    multi = mode == "recipe" and categories is None and get_recipe(effective_room_type) is not None
    if not multi:
        resp = plan_assist_layout(room, preferences, placed_items, categories, room_type)
        return [("Suggested layout", True, resp)]
    try:
        variants = plan_layout_variants(room, preferences, placed_items, room_type, max_variants)
    except Exception:  # noqa: BLE001 - never break the request; fall back to a single layout
        logger.exception("assist templates[%s]: variant generation failed; single layout", effective_room_type)
        return [("Suggested layout", True, plan_assist_layout(room, preferences, placed_items, categories, room_type))]
    logger.info(
        "assist templates[%s]: %d option(s) %s",
        effective_room_type, len(variants), [lbl for lbl, _ in variants],
    )
    return [(lbl, i == 0, resp) for i, (lbl, resp) in enumerate(variants)]


def plan_assist_layout(
    room: Room,
    preferences: Preferences,
    placed_items: list[PlacedItem],
    categories: list[str] | None = None,
    room_type: str | None = "living_room",
) -> AssistLayoutResponse:
    """Mode-aware entry point for /assist/layout (ASSIST_PLANNER_MODE).

    legacy  - current planner only (zero overhead).
    recipe  - recipe planner; safely falls back to legacy when no recipe is registered
              or a `categories` override is given; propagates a clear RecipeError only if
              the recipe path itself fails.
    shadow  - legacy is PRIMARY and returned to the user; the recipe path runs alongside,
              is compared, and divergences are logged. Any recipe failure is swallowed so
              the user request never breaks.
    """
    mode = get_settings().assist_planner_mode
    if mode == "legacy":
        return plan_layout(room, preferences, placed_items, categories, room_type)

    effective_room_type = preferences.room_type or room_type or "living_room"
    recipe_applicable = categories is None and get_recipe(effective_room_type) is not None

    if mode == "recipe":
        if not recipe_applicable:
            # categories-override decision (Option A, lower risk): route overrides and
            # unknown room types to the legacy planner. TODO(recipe): support categories
            # overrides natively, or deprecate them once usage is confirmed ~zero.
            logger.info(
                "assist recipe[%s]: routed to legacy (%s)",
                effective_room_type,
                "categories override" if categories is not None else "no recipe registered",
            )
            return plan_layout(room, preferences, placed_items, categories, room_type)

        try:
            result = plan_layout_from_recipe(room, preferences, placed_items, room_type)
        except Exception:  # noqa: BLE001 - recipe mode surfaces failures clearly (see log)
            logger.exception(
                "assist recipe[%s]: recipe planner FAILED - roll back with ASSIST_PLANNER_MODE=legacy",
                effective_room_type,
            )
            raise

        recipe = get_recipe(effective_room_type)
        hard = sum(1 for f in result.findings if f.severity == "error")
        logger.info(
            "assist recipe[%s]: %s recipe=%s@%s placements=%d skipped=%d hard=%d",
            effective_room_type, result.proposal_id, recipe.recipe_id, recipe.version,
            len(result.placements), len(result.skipped), hard,
        )
        return result

    # shadow: legacy is the source of truth for the user; recipe runs for comparison.
    legacy_result = plan_layout(room, preferences, placed_items, categories, room_type)
    if recipe_applicable:
        try:
            recipe_result = plan_layout_from_recipe(room, preferences, placed_items, room_type)
            cmp = compare_layouts(legacy_result, recipe_result)
            if cmp.equivalent:
                logger.info(
                    "assist shadow[%s]: EQUIVALENT (proposal_id_match=%s)",
                    effective_room_type, cmp.proposal_id_match,
                )
            else:
                logger.warning("assist shadow[%s]: DIVERGENCE %s", effective_room_type, "; ".join(cmp.diffs))
        except Exception:  # noqa: BLE001 - shadow must never break the user request
            logger.exception("assist shadow[%s]: recipe path failed; returning legacy", effective_room_type)
    return legacy_result
