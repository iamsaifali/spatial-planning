"""Whole-room auto-planner for the "Assist with AI" feature.

Composes the EXISTING deterministic spatial + recommendation engine to propose a
complete furniture layout in a single pass. Critically, no LLM or image model is
involved in choosing coordinates:

  * products are chosen by recommend.selector.select_slots (deterministic scoring)
  * poses are chosen by the spatial engine (suggest_pose -> settle -> autofix)
  * every placement is checked by spatial.validate.validate_item before it is kept

The rationale strings are template text built from machine-checked facts, not an
LLM. (An LLM may later phrase nicer copy, but never the geometry.)

The living_room flow places one best product per category; bedroom adds mirrored
nightstands. Every flow shares one response builder.
"""

import hashlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count

from spatial_planning.config import get_settings
from spatial_planning.models.api import (
    SKIP_DID_NOT_FIT,
    AssistLayoutResponse,
    AssistPlacement,
    AssistSkip,
    AssistTotals,
)
from spatial_planning.models.geometry import PlacedItem, Pose, Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import (
    CATEGORY_LABELS,
    SOFA_LADDER,
    SOFA_RANK,
    SOFA_TYPE_CATEGORY,
    Product,
    expected_max_width,
    placement_group,
    seat_target_for_area,
)
from spatial_planning.models.validation import MUST_FIX_CODES, Finding
from spatial_planning.handlers._common import PlacedProduct, resolve_placed, wall_label
from spatial_planning.services.catalog import CatalogRepository, get_repository
from spatial_planning.services.guide.flow import sequence_for_room_type
from spatial_planning.services.recommend.selector import Candidate, select_slots
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.autofix import find_autofix, settle_pose, suggest_pose
from spatial_planning.services.spatial.core import RoomAnalysis, ZoneData
from spatial_planning.services.spatial.validate import validate_item
from spatial_planning.services.recipe.equivalence import compare_layouts
from spatial_planning.services.recipe import pieces
from spatial_planning.services.recipe.models import CountRule, Recipe, RoleDefinition
from spatial_planning.services.recipe.predicates import resolve_predicate
from spatial_planning.services.recipe.registry import get_recipe
from spatial_planning.services.recipe.strategies import resolve_strategy
from spatial_planning.services.spatial.geometry_utils import item_polygon
from spatial_planning.services.spatial.zones import (
    MAX_RETURN_SOFAS,
    CategoryStats,
    anchor_pose,
    zones_for_category,
)

logger = logging.getLogger("zory")

# Proposed items get deterministic, recognisable ids; the front-end re-mints real
# ids when the user accepts so accepted items never collide with existing ones.
AUTO_PREFIX = "auto-"


class RecipeError(RuntimeError):
    """Raised when the recipe-driven planner cannot run (e.g. no recipe registered)."""


def _default_seat_target(analysis: RoomAnalysis) -> int:
    """Sensible seating-capacity target from room area when none is supplied."""
    return seat_target_for_area(analysis.area_cm2)


# Human phrases (with the right article) for the honour-then-size-down notice.
_SOFA_PHRASE = {"2-seater-sofa": "a 2-seater", "3-seater-sofa": "a 3-seater", "l-shape-sofa": "an L-shape"}


def _sofa_ladder(prefs: Preferences) -> list[str | None]:
    """Store categories to try for the PRIMARY sofa, honoured choice first then sizing DOWN.

    - "auto" -> [None]: the selector derives the size from room area (today's behaviour).
    - a compact re-plan (compact_seating) forces a 2-seater (+ chair), whatever Q2 asked.
    - an explicit Q2 choice starts at that size and sizes DOWN the ladder if it can't place.
    """
    if prefs.compact_seating:
        return ["2-seater-sofa"]
    if prefs.sofa_type == "auto":
        return [None]
    start = SOFA_TYPE_CATEGORY[prefs.sofa_type]
    return list(SOFA_LADDER[SOFA_LADDER.index(start):])


def _rationale(category: str, zone: ZoneData, analysis: RoomAnalysis) -> str:
    """Deterministic, template-only explanation (no LLM) from the chosen zone."""
    label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
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
    have_categories = {placement_group(product.category) for _i, product in working}

    sequence = categories if categories is not None else sequence_for_room_type(effective_room_type)

    placements: list[AssistPlacement] = []
    skipped: list[AssistSkip] = []
    ids = count(1)

    for category in sequence:
        # Respect the user's own items: don't add a second essential they placed.
        if category in have_categories:
            skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
            continue

        zones = zones_for_category(category, analysis, working, stats, room_type=effective_room_type)
        result = select_slots(category, zones, preferences, working, repo, room_area_cm2=analysis.area_cm2)
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
# enforced by tests + shadow mode). The legacy plan_layout is left untouched as the
# equivalence reference.
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
    # Human-readable planner messages (size-down / seat-count shortfall) surfaced on the
    # response.notices channel alongside the Phase 1 "didn't fit" gating notices.
    notices: list[str] = field(default_factory=list)
    have_categories: set[str] = field(default_factory=set)
    ids: Iterator[int] = field(default_factory=lambda: count(1))
    # Per-role bookkeeping for checklist gating notices (Phase 1): how many instances each
    # role placed, and the last skip it emitted (used to turn "requested but placed zero"
    # into a "didn't fit" notice). Keyed by role name so the decor duplicate (plant vs
    # vases, same category) is disambiguated.
    placed_by_role: dict[str, int] = field(default_factory=dict)
    skip_by_role: dict[str, AssistSkip] = field(default_factory=dict)
    # role -> a pinned zone (template generation forces the primary piece onto a chosen
    # wall; every other role still resolves normally and cascades around it)
    zone_overrides: dict[str, ZoneData] = field(default_factory=dict)
    # Phase 4: was a TV UNIT actually requested (in the active checklist set)? Default True
    # (TV-included is the essentials default and every golden). When False the room is
    # conversation-focal: the sofa's window-wall avoidance relaxes (see _run_strategy /
    # _sofa_zones) and the TV-shaped template ranking/drops are skipped.
    tv_requested: bool = True


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


def active_roles(recipe: Recipe, preferences: Preferences, room_type: str) -> list[RoleDefinition]:
    """The recipe roles to execute, after checklist gating (Phase 1).

    CORE roles (a role that maps to a core piece, or to NO checklist piece at all — e.g.
    the L-return `secondary_seating`) ALWAYS run. CHECKLIST roles (essentials + optionals)
    run only when their piece key is in the active set: `preferences.included_pieces` if
    given, else the essentials-only default. Gating applies to any room type WITH a piece
    table (living_room, bedroom); every other room type runs its recipe unchanged.

    Pure filter over `recipe.roles` (declared order preserved) — it never reorders, so
    opting in every mapped piece reproduces the ungated layout byte-for-byte.
    """
    if room_type not in pieces._ROOM_PIECES:
        return list(recipe.roles)
    active = pieces.resolve_active_pieces(preferences.included_pieces, room_type)
    kept: list[RoleDefinition] = []
    for role in recipe.roles:
        pc = pieces.piece_for_role(role.role, room_type)
        if pc is None or pc.tier == "core" or pc.key in active:
            kept.append(role)
    return kept


def _tv_requested(preferences: Preferences, room_type: str) -> bool:
    """Phase 4 signal — was a TV UNIT REQUESTED (INTENT), not "was one placed".

    The active checklist set = `preferences.included_pieces` if given, else the essentials-only
    default (which INCLUDES `tv_unit`). So `included_pieces=None` -> True (unchanged), a list
    OMITTING `tv_unit` -> False (conversation-focal, relax the TV rules), a list including it -> True.
    A TV requested but that didn't fit is still True (not a no-TV case). Non-living rooms and the
    legacy path are always True — the checklist feature is living-room only, so nothing changes there.
    """
    if room_type != "living_room":
        return True
    return "tv_unit" in pieces.resolve_active_pieces(preferences.included_pieces)


def _side_shift_mode(preferences: Preferences, room_type: str) -> str | None:
    """Should the great-room conversation group slide to one side? ONLY when a DINING table was requested
    - so the dining set gets a comfortable freed block beside the group. Otherwise the group stays
    CENTRED, whether it's an L-return or a U-return (a U with no dining is centred, same as an L). The
    shift is "bounded": it leaves room on the NEAR (wall) flank for the secondary sofa / a companion
    chair, so nothing gets jammed or stranded. Living-room only; `_sofa_zones` still requires a great
    room + real lateral slack before it acts."""
    if room_type != "living_room":
        return None
    if "dining_set" in pieces.resolve_active_pieces(preferences.included_pieces):
        return "bounded"
    return None


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
    params = role.zone_strategy.params
    # Phase 4: thread the "no TV requested" signal into the zone strategy so _sofa_zones can
    # relax its window-wall avoidance. Only injected when NO TV was requested, so a TV-included
    # plan passes the recipe's params dict UNCHANGED (strict no-op, byte-identical goldens).
    if not st.tv_requested:
        params = {**params, "tv_requested": False}
    # Great-room lateral side-shift: only when a dining table was requested, or a U formed (see
    # _side_shift_mode). Otherwise the group stays centred.
    mode = _side_shift_mode(st.preferences, st.room_type)
    if mode is not None:
        params = {**params, "side_shift_mode": mode}
    # Thread the role's store_category pin so a strategy can tell WHICH piece of a shared placement
    # group it is placing (e.g. the bedroom `vanity` role pins "dressing-table" within the `storage`
    # group). Strategies that don't read it ignore the extra key, so other roles stay byte-identical.
    if role.store_category is not None:
        params = {**params, "store_category": role.store_category}
    return strategy.resolver(category, st.room_type, st.analysis, st.working, st.stats, params)


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


def _execute_primary_sofa(role: RoleDefinition, st: _PlanState) -> None:
    """Place the PRIMARY living-room sofa, honouring the Q2 sofa_type then sizing DOWN.

    Q2 (prefs.sofa_type) pins the primary sofa's form; if the chosen size can't be selected
    or placed in this room, we walk DOWN the ladder (l-shape -> 3-seater -> 2-seater) and
    surface a notice, so a room is never left sofa-less (honour-then-size-down, CLAUDE.md 5.1).
    "auto" preserves today's area-derived default (the first rung is the selector's own
    resolution). The L-return (secondary_seating) is unaffected - it stays a 2-seater."""
    category = role.categories[0]
    pinned = st.zone_overrides.get(role.role)
    requested = SOFA_TYPE_CATEGORY.get(st.preferences.sofa_type)  # None for "auto"
    last_reason = "NO_FIT"
    for store_cat in _sofa_ladder(st.preferences):
        zones = [pinned] if pinned is not None else _run_strategy(role, category, st)
        result = select_slots(
            category, zones, st.preferences, st.working, st.repo,
            room_area_cm2=st.analysis.area_cm2, store_category=store_cat,
        )
        candidate = result.best
        if candidate is None:
            last_reason = str(result.no_fit_hints.get("reason", "NO_FIT"))
            continue
        pose = settle_pose(
            st.analysis, st.working, candidate.product,
            anchor_pose(candidate.zone, candidate.product, st.analysis),
        )
        placement, item, reason = _commit(
            category, candidate, pose, candidate.zone.id, f"{AUTO_PREFIX}{next(st.ids)}", st.analysis, st.working
        )
        if placement is None:
            last_reason = reason or "NO_VALID_SPOT"
            continue
        st.placements.append(placement)
        st.working.append((item, candidate.product))
        st.have_categories.add(category)
        # Honour-then-size-down notice: the sofa we placed is smaller than the user's explicit
        # Q2 choice (only meaningful when the catalog has distinct sofa store categories).
        placed_cat = candidate.product.category
        if requested and placed_cat in SOFA_RANK and SOFA_RANK[placed_cat] < SOFA_RANK[requested]:
            st.notices.append(
                f"We used {_SOFA_PHRASE[placed_cat]} — {_SOFA_PHRASE[requested]} "
                "wouldn't fit this room comfortably."
            )
        return
    st.skipped.append(AssistSkip(category=category, reason=last_reason))
    st.have_categories.add(category)


def _execute_single(role: RoleDefinition, st: _PlanState) -> None:
    category = role.categories[0]
    if category in st.have_categories and not role.allow_duplicate:
        st.skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
        return

    # The living-room primary sofa owns Q2 (sofa_type) + the honour-then-size-down ladder.
    if st.room_type == "living_room" and role.role == "primary_seating":
        _execute_primary_sofa(role, st)
        return

    pinned = st.zone_overrides.get(role.role)
    zones = [pinned] if pinned is not None else _run_strategy(role, category, st)
    # Honour a role's explicit store_category pin (e.g. work_seat -> office-chair, console vases -> vase),
    # like the fill/per-anchor/secondary executors already do. None -> the room preference, as before.
    result = select_slots(category, zones, st.preferences, st.working, st.repo,
                          room_area_cm2=st.analysis.area_cm2, store_category=role.store_category)
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

        result = select_slots(category, [zone], st.preferences, st.working, st.repo, room_area_cm2=st.analysis.area_cm2)
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


def _execute_secondary_sofa(role: RoleDefinition, st: _PlanState) -> None:
    """Living-room secondary seating: fill the primary's flanks with RETURN sofas SIZED TO THE SEAT GAP
    (the sofa-first fill ladder, CLAUDE.md 5.1).

    Gated on an EXPLICIT seat request: only when the user SET `seating_capacity` (Q1) does this build a U
    - gap-sized returns (3-seater vs 2-seater) on both flanks up to `MAX_RETURN_SOFAS`, sized DOWN if a
    size won't fit. On AUTO (area-derived default, no explicit ask) it keeps today's backbone: a single
    2-seater L-return - so opt-in pieces (chaise, console) still fit and the AUTO goldens are unchanged.
    The FIRST return is placed for any positive gap (the "never a lone 3-seater" backbone); ADDITIONAL
    returns only when the gap is worth a whole sofa - a smaller leftover (+1) is left to a chair
    (companion_seating). Small rooms / a met target yield no return (the zone generator's area guard + the
    gap gate). Never sofa-less: the primary already placed via _execute_primary_sofa's honour-then-size-down."""
    category = role.categories[0]  # "sofa"
    metric = role.count.metric or "seating_capacity"
    target = _count_target(role.count, st)
    strategy = resolve_strategy(role.zone_strategy.name)
    explicit = st.preferences.seating_capacity is not None
    max_returns = MAX_RETURN_SOFAS if explicit else 1  # AUTO: today's single 2-seater L-return backbone

    def _return_seats(store_cat: str) -> int:
        # catalog-derived: a "2-seater-sofa" (~200cm) can actually seat 3, so never key the ladder on
        # literal 2/3 - ask the catalog what each return size seats (smallest, to be conservative).
        prods = [p for p in st.repo.in_category("sofa") if p.category == store_cat]
        return int(min((p.seating_capacity for p in prods), default=(4 if store_cat == "3-seater-sofa" else 3)))

    two_seats = _return_seats("2-seater-sofa")   # the smallest return worth placing (a chair covers a <2-seater gap)
    three_seats = _return_seats("3-seater-sofa")

    def _zones_for(store_cat: str) -> list[ZoneData]:
        params = {**role.zone_strategy.params, "return_category": store_cat}
        if not st.tv_requested:
            params["tv_requested"] = False
        return strategy.resolver(category, st.room_type, st.analysis, st.working, st.stats, params)

    used: set = set()
    returns_placed = 0
    while returns_placed < max_returns:
        seated = sum(_metric_of(p, metric) for _i, p in st.working if _metric_of(p, metric) > 0)
        gap = target - seated
        if gap <= 0:
            break
        if returns_placed >= 1 and gap < two_seats:
            break  # the target is all-but-met; a small leftover is a chair's job, not another sofa
        # AUTO: always today's 2-seater L-return. EXPLICIT: the largest size the gap can use (3s then 2s).
        ladder = ["3-seater-sofa", "2-seater-sofa"] if (explicit and gap >= three_seats) else ["2-seater-sofa"]
        placed_this = False
        for store_cat in ladder:  # largest the gap can use, then size DOWN until a free flank fits
            zone = next((z for z in _zones_for(store_cat) if _unit_key(z, role.count.one_per) not in used), None)
            if zone is None:
                continue
            result = select_slots(
                category, [zone], st.preferences, st.working, st.repo,
                room_area_cm2=st.analysis.area_cm2, store_category=store_cat,
            )
            candidate = result.best
            if candidate is None:
                continue
            pose = settle_pose(st.analysis, st.working, candidate.product, anchor_pose(zone, candidate.product, st.analysis))
            placement, item, _reason = _commit(
                category, candidate, pose, zone.id, f"{AUTO_PREFIX}{next(st.ids)}", st.analysis, st.working
            )
            if placement is None:
                continue
            used.add(_unit_key(zone, role.count.one_per))
            st.placements.append(placement)
            st.working.append((item, candidate.product))
            returns_placed += 1
            placed_this = True
            break
        if not placed_this:
            break  # no return size fits a free flank -> stop (chairs top up any remainder)
    st.have_categories.add(category)


def _execute_mirror_pair(role: RoleDefinition, st: _PlanState) -> None:
    """Place one item per side zone the strategy produced (left + right), each gated.

    Used for bedroom nightstands: 2 when both sides of the bed are clear, 1 when only
    one fits, 0 (skip) when neither does. The strategy already carves out door/window
    keep-out, and the gate validates every placement - so this never blocks a door.
    """
    category = role.categories[0]
    # Respect allow_duplicate (consistent with _execute_single / _execute_fill_available): a role flagged
    # allow_duplicate runs even when its placement group is already placed - e.g. the bedside lampshades
    # (mirror pair) must NOT be skipped just because a corner / lounge FLOOR-stand claimed `lighting` first.
    if category in st.have_categories and not role.allow_duplicate:
        st.skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
        return

    zones = _run_strategy(role, category, st)  # up to two side zones (left, right)
    placed_any = False
    for zone in zones[: (role.count.max or 2)]:
        result = select_slots(category, [zone], st.preferences, st.working, st.repo, room_area_cm2=st.analysis.area_cm2)
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
    if category in st.have_categories and not role.allow_duplicate:
        st.skipped.append(AssistSkip(category=category, reason="ALREADY_PRESENT"))
        return

    zones = _run_strategy(role, category, st)
    if st.room_type == "living_room" and role.role == "companion_seating":
        # Sofa-first ladder: accent chairs are the LAST resort and GAP-driven, NOT area-scaled.
        # Place only enough to top up the seat target the sofa group (primary + L-return)
        # couldn't reach - cap = clamp(target - seats already placed, 0, max) - so a room that
        # the sofas already seat gets zero chairs, and an odd +1 tops up (CLAUDE.md 5.1).
        target = st.preferences.seating_capacity or _default_seat_target(st.analysis)
        # The chaise-lounge is a standalone LOUNGE piece, not conversation seating - exclude it from the
        # seat tally so opting it in never shrinks the sofa/chair set toward the target.
        seated = sum(
            _metric_of(p, "seating_capacity") for _i, p in st.working
            if _metric_of(p, "seating_capacity") > 0 and placement_group(p.category) != "chaise"
        )
        cap = max(0, min(role.count.max or 2, target - seated))
    else:
        area_m2 = st.analysis.area_cm2 / 10_000.0
        per = role.count.per_area_m2 or 12.0
        cap = max(1, round(area_m2 / per))
        if role.count.max is not None:
            cap = min(cap, role.count.max)

    placed = 0
    for zone in zones:
        if placed >= cap:
            break
        result = select_slots(
            category, [zone], st.preferences, st.working, st.repo,
            room_area_cm2=st.analysis.area_cm2, store_category=role.store_category,
        )
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

    # cap == 0 is an INTENTIONAL "no more seats needed" (gap-driven chairs), not a fit failure -
    # only flag NO_FIT when we actually tried (cap > 0) and nothing landed.
    if placed == 0 and cap > 0:
        st.skipped.append(AssistSkip(category=category, reason="NO_FIT"))
    st.have_categories.add(category)


def _execute_per_anchor(role: RoleDefinition, st: _PlanState) -> None:
    """Place one item per candidate zone the strategy rings around an anchor (dining chairs
    around the dining table). Every candidate is gated by _commit; a position that can't fit
    (crowded against a wall, or the anchor never placed -> no zones) is simply SKIPPED — fewer
    is fine. Bounded by role.count.max. Unlike the other executors this NEVER touches
    have_categories: the ring shares its placement group (accent_chair) with the companion
    chairs, and marking it present would wrongly gate them (they run first regardless)."""
    category = role.categories[0]
    zones = _run_strategy(role, category, st)
    placed_any = False
    for zone in zones[: (role.count.max or len(zones))]:
        result = select_slots(
            category, [zone], st.preferences, st.working, st.repo,
            room_area_cm2=st.analysis.area_cm2, store_category=role.store_category,
        )
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


def _execute_role(role: RoleDefinition, st: _PlanState) -> None:
    mode = role.count.mode
    before_placed, before_skipped = len(st.placements), len(st.skipped)
    if st.room_type == "living_room" and role.role == "secondary_seating":
        _execute_secondary_sofa(role, st)  # gap-sized L/U of return sofas (living-room seating ladder)
    elif mode == "single":
        _execute_single(role, st)
    elif mode == "until_target":
        _execute_until_target(role, st)
    elif mode == "mirror_pair":
        _execute_mirror_pair(role, st)
    elif mode == "fill_available":
        _execute_fill_available(role, st)
    elif mode == "per_anchor":
        _execute_per_anchor(role, st)
    else:
        raise RecipeError(f"count mode '{mode}' is not implemented yet (role '{role.role}')")
    # Bookkeeping for gating notices: record what THIS role placed / skipped (by role name,
    # so two roles sharing a category — plant & vases are both 'decor' — stay distinct).
    st.placed_by_role[role.role] = len(st.placements) - before_placed
    new_skips = st.skipped[before_skipped:]
    if new_skips:
        st.skip_by_role[role.role] = new_skips[-1]


def _apply_gating_notices(
    resp: AssistLayoutResponse, preferences: Preferences, room_type: str, st: _PlanState
) -> None:
    """Honest 'didn't fit' notices, for any room type WITH a piece table (living_room, bedroom).

    For every checklist piece the user REQUESTED (in the active set) whose role ran but
    placed zero instances, mark its skip `SKIP_DID_NOT_FIT` and append a human-readable
    line to `resp.notices` (e.g. "The reading chair didn't fit this room." when the user
    opted into both a dressing table and a reading chair in a room that only holds one).
    Excluded pieces produce no skip (their role never ran) and core shortfall is out of
    scope, so neither is notified. A piece the user already placed (ALREADY_PRESENT) is
    present, not unfit — no notice.
    """
    if room_type not in pieces._ROOM_PIECES:
        return
    for key in pieces.resolve_active_pieces(preferences.included_pieces, room_type):
        pc = pieces.piece(key, room_type)
        if pc is None or pc.tier == "core" or pc.role is None:
            continue  # core / role-less (dining_set) — nothing ran to notice
        if st.placed_by_role.get(pc.role, 0) > 0:
            continue  # requested and placed — no notice
        skip = st.skip_by_role.get(pc.role)
        if skip is None or skip.reason == "ALREADY_PRESENT":
            continue  # role didn't run, or the user already placed it
        skip.reason = SKIP_DID_NOT_FIT
        resp.notices.append(f"The {pc.label.lower()} didn't fit this room.")


def _apply_seating_notices(
    resp: AssistLayoutResponse, preferences: Preferences, room_type: str
) -> None:
    """Seat-count rounds UP, never under: when even the smallest clean arrangement over-fills
    the room the ladder walks DOWN (fewer sofas/chairs) and we say how many it actually seats.
    Only surfaced when the user gave an EXPLICIT count and the placed seating fell short."""
    if room_type != "living_room" or preferences.seating_capacity is None:
        return
    # The chaise-lounge is a standalone lounge piece, not conversation seating - it doesn't count toward
    # "comfortably seats N".
    seated = sum(
        p.product.seating_capacity for p in resp.placements
        if p.product.seating_capacity > 0 and placement_group(p.category) != "chaise"
    )
    if 0 < seated < preferences.seating_capacity:
        resp.notices.append(f"This room comfortably seats {seated}.")


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
        have_categories={placement_group(product.category) for _i, product in working},
        zone_overrides=zone_overrides or {},
        tv_requested=_tv_requested(preferences, effective_room_type),
    )

    # Gate the recipe to the requested checklist pieces. Topologically order the FULL recipe
    # (so a dependency filtered out below still linearises without error), then execute only
    # the active roles — a filtered role is thus equivalent to being absent/skipped.
    active = {r.role for r in active_roles(recipe, preferences, effective_room_type)}
    for role in _topological_order(recipe.roles):
        if role.role in active:
            _execute_role(role, st)

    resp = _finalize_response(st.analysis, st.placements, st.skipped, st.working)

    # Never a LONE 3-seater (nor a 3-seater + lone chair): a 3-seater primary that couldn't get its
    # L-return (a narrow room, or windows on both long walls) re-plans ONCE with a COMPACT 2-seater
    # primary - which pairs with an accent chair (or a 2-seater L-return where the slimmer piece fits).
    # A room thus always resolves to (3-seater + L-return) or (2-seater + chair), never a lone sofa.
    # This "never lone" rule only applies to the AUTO sofa path (the SYSTEM chose the 3-seater, so a
    # lone one would look sparse). When the user EXPLICITLY pinned a sofa type (sofa_type != "auto"),
    # honour it: a lone 3-seater that physically fits stays - it is not compacted to a 2-seater just
    # because there is no room for an L-return. (A genuine physical non-fit is still handled earlier by
    # the honour-then-size-down ladder in _execute_primary_sofa.)
    if (
        effective_room_type == "living_room"
        and not preferences.compact_seating
        and preferences.sofa_type == "auto"
    ):
        sofas = [p for p in resp.placements if p.category == "sofa"]
        if len(sofas) == 1 and sofas[0].product.category == "3-seater-sofa":
            return plan_layout_from_recipe(
                room,
                preferences.model_copy(update={"compact_seating": True}),
                placed_items,
                room_type,
                zone_overrides,
            )
    resp.notices.extend(st.notices)  # size-down / honour-then-size-down messages from this pass
    _apply_seating_notices(resp, preferences, effective_room_type)
    _apply_gating_notices(resp, preferences, effective_room_type, st)
    return resp


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


def _template_layout_score(
    resp: AssistLayoutResponse, analysis: RoomAnalysis, tv_requested: bool = True
) -> float:
    """A design-quality score used to rank/recommend templates. Today it rewards a working
    sofa<->TV pair (the TV actually faces the sofa, at a comfortable distance) - so we
    recommend a sofa wall whose opposite wall can host the TV, instead of one where the TV
    gets pushed to a side wall - and, in a clearly rectangular room, a sofa on a LONG wall
    facing ACROSS the SHORTER span (a comfortable viewing distance) over one on a SHORT wall
    facing down the long axis. 0 for rooms without a sofa+TV (e.g. bedrooms), leaving their
    order unchanged.

    Phase 4: when no TV was REQUESTED (`tv_requested=False`), the TV terms (in-front reward,
    viewing distance, off-centre penalty) are SKIPPED - a conversation-focal room must never be
    ranked on a TV it doesn't have - while the TV-independent terms (long-axis balance, tight
    L-return, companion-chair proximity, warnings) still rank the walls."""
    from spatial_planning.services.spatial.geometry_utils import front_vector, item_polygon

    sofas = [p for p in resp.placements if p.category == "sofa"]
    tvs = [p for p in resp.placements if p.category == "tv_unit"]
    if not sofas:
        return 0.0
    if tv_requested and not tvs:
        return 0.0  # a TV-focal room with no TV placed is degenerate - leave its order unchanged
    sofa = sofas[0]  # sofas[0] is the PRIMARY (placed first); an L-return is 2nd
    f = front_vector(sofa.pose.rotation_deg)
    # Viewing-distance / room-shape preference: in a clearly rectangular room a sofa facing
    # ACROSS the SHORTER span sits on a LONG wall a comfortable distance from its TV on the
    # opposite wall; one facing DOWN the LONGER span pushes the TV far away and leaves a
    # lopsided, half-empty room. Penalise facing along the long axis so a long-wall template
    # outranks a short-wall one (near-square rooms fail the guard, so are unaffected).
    minx, miny, maxx, maxy = analysis.polygon.bounds
    rw, rh = maxx - minx, maxy - miny
    if abs(rw - rh) > 60.0:
        long_axis = (1.0, 0.0) if rw >= rh else (0.0, 1.0)
        along_long = abs(f[0] * long_axis[0] + f[1] * long_axis[1])
        score_long_axis_penalty = 2.0 * along_long
    else:
        score_long_axis_penalty = 0.0
    score = 0.0
    if tv_requested:  # tvs guaranteed present here (early-returned above otherwise)
        tv = tvs[0]
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
        # the TV should sit CENTRED in front of the sofa, not shoved to one side
        score -= min(1.5, abs(vy * f[0] - vx * f[1]) / 60.0)
    # a big-room L-return should form a TIGHT adjacent L, not a second sofa floating in the
    # middle of the room: reward a small gap between the two sofas, penalise a large one
    if len(sofas) >= 2:
        a = item_polygon(sofas[0].pose.x, sofas[0].pose.y, sofas[0].product.width_cm, sofas[0].product.depth_cm, sofas[0].pose.rotation_deg)
        b = item_polygon(sofas[1].pose.x, sofas[1].pose.y, sofas[1].product.width_cm, sofas[1].product.depth_cm, sofas[1].pose.rotation_deg)
        gap = a.distance(b)
        score += 1.0 if gap < 35.0 else (0.4 if gap < 130.0 else -0.9)
    # penalise ANY layout issue, so a template with warnings ranks below a clean one
    _WARN = {"BLOCKS_WALKWAY": 3.0, "TV_TOO_CLOSE": 1.5, "FRONT_BLOCKED": 1.5,
             "CLEARANCE_TOO_TIGHT": 0.8, "NARROWS_WALKWAY": 0.5, "DOMINATES_ROOM": 0.8,
             "BLOCKS_WINDOW": 0.5}
    for fnd in resp.findings:
        score -= _WARN.get(fnd.code, 0.3 if fnd.severity == "warning" else 0.0)
    # An accent chair is companion seating - it belongs CLOSE to the sofa (a conversation group), not
    # stranded across the room. Penalise a chair that drifts far from the sofa, so a template that
    # seats it BESIDE the sofa outranks one that exiles it to a far corner. (Soft: it re-orders, never
    # drops - a room whose only option is a far chair still surfaces it.)
    chairs = [p for p in resp.placements if p.category == "accent_chair"]
    if chairs:
        cd = min(((c.pose.x - sofa.pose.x) ** 2 + (c.pose.y - sofa.pose.y) ** 2) ** 0.5 for c in chairs)
        score -= min(2.0, max(0.0, (cd - 250.0) / 120.0))
    # Penalise a primary sofa FLOATED far off its back wall with DEAD (empty) space behind it: that strip
    # is unreachable, wasted, and the floated sofa eats into the walking space (the "dead back area"). A
    # sofa hugging its wall - or one with a console/storage tucked into the gap (a deliberate great-room
    # move that USES the space) - is NOT penalised. This favours the hugging long-wall layout over one
    # that floats a sofa off a short wall (common in a wide room) just to shorten the viewing distance.
    back_wall = max(analysis.walls, key=lambda wl: wl.normal[0] * f[0] + wl.normal[1] * f[1])
    back_gap = (
        (sofa.pose.x - back_wall.start[0]) * back_wall.normal[0]
        + (sofa.pose.y - back_wall.start[1]) * back_wall.normal[1]
        - sofa.product.depth_cm / 2.0
    )
    if back_gap > 45.0:
        wperp = (-f[1], f[0])  # along the sofa's width (the wall direction)
        behind_used = any(
            (not p.product.is_walkable) and p.category != "sofa"
            and ((p.pose.x - sofa.pose.x) * (-f[0]) + (p.pose.y - sofa.pose.y) * (-f[1])) > sofa.product.depth_cm / 2.0
            and abs((p.pose.x - sofa.pose.x) * wperp[0] + (p.pose.y - sofa.pose.y) * wperp[1]) < sofa.product.width_cm / 2.0 + 30.0
            for p in resp.placements
        )
        if not behind_used:
            score -= min(2.0, (back_gap - 45.0) / 40.0)
    score -= score_long_axis_penalty
    # Reward a template that satisfies the WHOLE checklist: penalise every piece the user opted into
    # that this arrangement couldn't fit (a `did_not_fit` skip - set by `_apply_gating_notices` for a
    # requested role that placed zero). So of two otherwise-comparable walls, the one that lands the
    # dining set AND the chaise outranks the one that drops one of them - the request is honoured where
    # geometry allows, and a template that omits an opted-in piece falls below one that keeps it.
    dropped = sum(1 for sk in resp.skipped if sk.reason == SKIP_DID_NOT_FIT)
    score -= 1.5 * dropped
    return score


# The TV must sit SQUARELY in front of the primary sofa: its centre aligned with the sofa's centre.
# A window that nudges the TV off-centre (to clear the glass) must NOT pass - such a template is
# rejected so a wall where the TV *can* centre on the sofa is surfaced instead. Small absolute slack
# only (rounding / a few cm of zone drift), NOT the sofa's half-width.
_TV_SOFA_CENTER_TOL_CM = 30.0

# BEDROOM analogue: a REQUESTED TV must sit SQUARELY in front of & centred on the BED (watchable from
# it). A TV pushed off the bed's centre-line (squeezed off by a window / a shorter solid run on the
# facing wall) must NOT surface - drop the template so a bed wall whose facing wall centres the TV is
# preferred instead. Same small absolute slack (zone drift), not the bed's half-width.
_TV_BED_CENTER_TOL_CM = 40.0

# NEVER surface a template where two REAL (non-walkable) pieces OVERLAP - even a graze that slips under
# validate_item's per-item overlap tolerance (e.g. a chaise settled a few cm into a sofa). A max-penalty
# template gate, stricter than the per-item validator, mirroring the door-swing gate. Small absolute area
# so a real overlap drops but touching pieces (an L-return meeting the primary, a chair at the dining
# table - both ~0 overlap) pass.
_TEMPLATE_OVERLAP_TOL_CM2 = 80.0
# Intentional ON-SURFACE overlaps that are NOT a defect (mirror of validate.py `_ON_SURFACE_PAIRS`):
# a lamp resting on a side table, vases/decor resting on a console/storage top.
_OVERLAP_EXEMPT_PAIRS = ({"lighting", "side_table"}, {"decor", "storage"})


def _template_has_overlap(resp: AssistLayoutResponse, _analysis: "RoomAnalysis | None" = None) -> bool:
    """A REAL overlap between two SOLID (non-walkable) pieces, past `_TEMPLATE_OVERLAP_TOL_CM2` and minus
    the intentional on-surface pairs. Used BOTH as a `_template_issues` drop AND in the final safety net
    (so an overlapping template can't leak through the last-resort fallback that bypasses `_template_issues`).
    Signature takes an optional analysis so it slots into the (resp, analysis) safety-net loop."""
    from spatial_planning.services.spatial.geometry_utils import item_polygon

    solid = [p for p in resp.placements if not p.product.is_walkable]
    for k in range(len(solid)):
        pk = item_polygon(solid[k].pose.x, solid[k].pose.y, solid[k].product.width_cm, solid[k].product.depth_cm, solid[k].pose.rotation_deg)
        for m in range(k + 1, len(solid)):
            if {solid[k].category, solid[m].category} in _OVERLAP_EXEMPT_PAIRS:
                continue  # a lamp on a table / vases on a console - intentional
            pm = item_polygon(solid[m].pose.x, solid[m].pose.y, solid[m].product.width_cm, solid[m].product.depth_cm, solid[m].pose.rotation_deg)
            if pk.intersection(pm).area > _TEMPLATE_OVERLAP_TOL_CM2:
                return True
    return False

# A surfaced template must keep the primary seating and the TV genuinely CLEAR of every door
# swing arc - not merely under the per-item validator's lenient 5% overlap tolerance (that slack
# exists for autofix leniency, not for what we RECOMMEND). Drop a template whose sofa/tv overlaps
# a swing arc at all, or hovers within this clearance of one (flush-at-0 and a few-cm sliver both
# read as "in the way of the door"). TEMPLATE-gate only; the per-item validate_item tolerance is
# untouched. Calibrated to KEEP a TV ~20 cm off the swing but DROP a flush/overlapping one.
_TEMPLATE_DOOR_CLEAR_CM = 10.0


# Roles whose collision with a door swing dooms a template: the substantial, non-walkable pieces a
# guest must NOT find parked across the entry - the sofa, the TV unit, the side table, and a
# console/storage cabinet. Small walkable/accent items (the rug is walkable; a plant or vases are
# minor) are deliberately excluded so they never drop an otherwise-clean template.
_DOOR_BLOCKING_ROLES = frozenset({"sofa", "tv_unit", "side_table", "storage"})

# The primary sofa must stay out of the door's straight-in WALK-IN lane - the rectangle you step into
# on entering. A sofa on the DOOR WALL crowds the entrance even when it clears the swing arc itself:
# a corner door makes the sofa overlap the swing (caught as a hard block), but a MID-wall door leaves
# the sofa just above the swing yet still jammed across the entry. Keyed on the walk-in LANE (not the
# swing, and NOT a corridor-width metric - that falsely fails a FLIP no-TV layout whose corridor a
# CHAIR legitimately pinches), so both door positions drop the same way. Only the deep ANCHOR (sofa)
# blocking the straight-in lane counts; small/flat pieces near a door don't obstruct a walk.
_ENTRY_APPROACH_DEPTH_CM = 150.0  # how far the walk-in lane reaches into the room from the door opening
_ENTRY_APPROACH_MARGIN_CM = 10.0  # widen the lane this much past each jamb
_SOFA_ENTRY_OVERLAP_CM2 = 500.0   # sofa footprint over the lane beyond this = crowds the entry
_SOFA_ENTRY_SIDE_CLEAR_CM = 60.0  # a sofa backing onto the DOOR wall within this of the swing = you enter alongside it

# When NO surfaced template can put the TV on a genuinely clear wall (solid, >=25cm off the door, and
# facing the sofa - see `_tv_is_clean`), the room simply has no TV wall. Rather than cram the TV onto
# glass or against the door, the engine SKIPS it and re-plans the room conversation-focal. This distinct
# notice tells the user WHY the TV is absent (vs the generic "didn't fit").
_NOTICE_TV_NO_CLEAR_WALL = (
    "TV skipped - no clear wall (solid, clear of the door, and facing the sofa) was available, "
    "so we arranged the room around conversation instead."
)


def _annotate_tv_skipped(resp: AssistLayoutResponse) -> None:
    """Mark a conversation-focal (Pass-2) template as an INTENTIONAL TV skip: the distinct notice plus
    an explicit skip record, so the frontend can show why the TV is absent."""
    resp.notices.append(_NOTICE_TV_NO_CLEAR_WALL)
    resp.skipped.append(AssistSkip(category="tv_unit", reason=SKIP_DID_NOT_FIT))


def _furniture_hits_door(resp: AssistLayoutResponse, analysis: RoomAnalysis) -> bool:
    """True when a SUBSTANTIAL piece in this template (sofa, TV, side table, or console/storage -
    see `_DOOR_BLOCKING_ROLES`) collides with a door: it intrudes on the swing arc / parks across
    the door OPENING (`blocked_door_geom`), OR it overlaps or hugs a swing arc within
    `_TEMPLATE_DOOR_CLEAR_CM` (a flush-at-0 touch or a sub-5%-overlap sliver that still slips past
    `validate_item`'s lenient per-item tolerance). A template like this must NEVER be surfaced, so
    this is checked BOTH in `_template_issues` (the normal gate) AND as a hard final filter on the
    surfaced rows (so a door-colliding option can't leak through the last-resort fallback when
    every template has some other issue). TEMPLATE-gate only - the per-item `validate_item` 5% swing
    tolerance is untouched."""
    from spatial_planning.services.spatial.geometry_utils import item_polygon
    from spatial_planning.services.spatial.validate import blocked_door_geom

    arcs = list(analysis.swing_arcs.values()) if analysis.swing_arcs else []
    for p in resp.placements:
        if placement_group(p.category) in _DOOR_BLOCKING_ROLES:
            ppoly = item_polygon(p.pose.x, p.pose.y, p.product.width_cm, p.product.depth_cm, p.pose.rotation_deg)
            if blocked_door_geom(analysis, p.product, ppoly) is not None:
                return True
            if arcs and min(ppoly.distance(a) for a in arcs) < _TEMPLATE_DOOR_CLEAR_CM:
                return True
    return False


def _furniture_blocks_door_hard(resp: AssistLayoutResponse, analysis: RoomAnalysis) -> bool:
    """The SEVERE half of `_furniture_hits_door`: a substantial piece that actually OVERLAPS the door
    swing (the door physically can't open past it) or parks across the door OPENING - as opposed to
    merely hovering within the comfort-clearance margin (`_TEMPLATE_DOOR_CLEAR_CM`) with the door
    still swinging free. Both are undesirable, but a sofa sitting IN the swing is categorically worse
    than a TV a few cm off it, so the surfaced-row filter drops these hard blockers first, keeping a
    softer template when one survives (see `plan_layout_variants`)."""
    from spatial_planning.services.spatial.geometry_utils import item_polygon
    from spatial_planning.services.spatial.validate import blocked_door_geom

    arcs = list(analysis.swing_arcs.values()) if analysis.swing_arcs else []
    for p in resp.placements:
        if placement_group(p.category) in _DOOR_BLOCKING_ROLES:
            ppoly = item_polygon(p.pose.x, p.pose.y, p.product.width_cm, p.product.depth_cm, p.pose.rotation_deg)
            if blocked_door_geom(analysis, p.product, ppoly) is not None:
                return True
            if any(ppoly.intersection(a).area > 25.0 for a in arcs):  # actually intrudes into the swing
                return True
    return False


def _sofa_blocks_entry(resp: AssistLayoutResponse, analysis: RoomAnalysis) -> bool:
    """The primary sofa sits across the door's straight-in WALK-IN lane, crowding the entrance - you
    squeeze past it stepping in. This is the general form of the "sofa on the entry" defect: a CORNER
    door makes the sofa overlap the swing (caught by `_furniture_blocks_door_hard`), but a MID-wall
    door leaves the sofa just above the swing yet still jammed across the walk-in. Build each door's
    approach lane (a rectangle from the opening, `_ENTRY_APPROACH_DEPTH_CM` deep along the inward
    normal, a margin past each jamb) and drop when the SOFA footprint overlaps it beyond
    `_SOFA_ENTRY_OVERLAP_CM2`. Only the deep anchor counts - a corridor-WIDTH metric was a dead end
    (it falsely fails a FLIP no-TV layout whose corridor a chair legitimately pinches). Checked as a
    HARD surfaced-row filter (the last-resort `_tv_in_front` pool bypasses `_template_issues`);
    dropped only when a clearer template survives, so the panel is never emptied.

    Two ways the sofa fouls the entry: (a) it sits ACROSS the straight-in lane (a corner/opposite-wall
    door), or (b) it BACKS ONTO the door wall right beside the swing - a mid-wall door on the sofa's own
    wall, so you step in alongside the sofa's back. The lane test catches (a); (b) needs its own check
    (the sofa is offset ALONG the wall from the door, not in front of it)."""
    from shapely.geometry import Polygon

    from spatial_planning.services.spatial.geometry_utils import front_vector, item_polygon

    sofas = [p for p in resp.placements if p.category == "sofa"]
    if not sofas or not analysis.room.doors:
        return False
    prim = max(sofas, key=lambda p: p.product.width_cm)
    ppoly = item_polygon(prim.pose.x, prim.pose.y, prim.product.width_cm, prim.product.depth_cm, prim.pose.rotation_deg)
    door_walls = {d.wall_index for d in analysis.room.doors}
    # (a) sofa across the door's straight-in walk-in lane
    for d in analysis.room.doors:
        w = analysis.walls[d.wall_index]
        p0 = w.point_at(d.offset_cm - _ENTRY_APPROACH_MARGIN_CM)
        p1 = w.point_at(d.offset_cm + d.width_cm + _ENTRY_APPROACH_MARGIN_CM)
        n, dep = w.normal, _ENTRY_APPROACH_DEPTH_CM
        lane = Polygon([
            (p0[0], p0[1]), (p1[0], p1[1]),
            (p1[0] + n[0] * dep, p1[1] + n[1] * dep),
            (p0[0] + n[0] * dep, p0[1] + n[1] * dep),
        ]).intersection(analysis.polygon)
        if not lane.is_empty and ppoly.intersection(lane).area > _SOFA_ENTRY_OVERLAP_CM2:
            return True
    # (b) sofa backs onto the DOOR wall, right beside the swing (you enter alongside its back)
    if analysis.swing_arcs:
        f = front_vector(prim.pose.rotation_deg)
        back_wall = max(range(len(analysis.walls)), key=lambda i: analysis.walls[i].normal[0] * f[0] + analysis.walls[i].normal[1] * f[1])
        if back_wall in door_walls and min(ppoly.distance(a) for a in analysis.swing_arcs.values()) < _SOFA_ENTRY_SIDE_CLEAR_CM:
            return True
    return False


def _template_issues(
    resp: AssistLayoutResponse, analysis: RoomAnalysis, tv_requested: bool = True, sofa_explicit: bool = False
) -> bool:
    """A template we should NOT surface at all: it has a layout warning, the TV isn't really in
    front of the sofa, the TV is shoved onto a WINDOW wall (squeezed beside/below the window),
    or a big-room second sofa FLOATS instead of forming an adjacent L.

    Phase 4: the TV-shaped drops (TV not in front, TV past the sofa edge, TV on a window wall,
    sofa facing down the long axis toward a far TV) apply ONLY when a TV was REQUESTED. A
    conversation-focal room is never dropped for a TV it doesn't have; the TV-independent drops
    (warnings, floating L-return, bed crammed on a door, oversized piece) still apply."""
    beds = [p for p in resp.placements if p.category == "bed"]
    # FRONT_BLOCKED is a SOFT advisory that fires routinely in a packed BEDROOM (bed + wardrobe +
    # dressing table + reading chair in one room); the blanket warning-drop would discard EVERY bedroom
    # template and force the fallback onto the worst bed wall. Ignore it for the drop decision when a bed
    # is present; every other warning still drops the template.
    if any(fd.severity == "warning" and not (beds and fd.code == "FRONT_BLOCKED") for fd in resp.findings):
        return True
    from spatial_planning.services.spatial.geometry_utils import front_vector, item_polygon

    sofas = [p for p in resp.placements if p.category == "sofa"]
    tvs = [p for p in resp.placements if p.category == "tv_unit"]
    # The sofa<->TV alignment gate is a LIVING-ROOM rule. In a BEDROOM the TV faces the BED (its own
    # bed<->TV gate below), and any sofa is a SEPARATE lounge - so the TV need not align with it. Running
    # this block in a bedroom wrongly drops every TV-placing template (the lounge sofa doesn't face the TV).
    if tv_requested and sofas and tvs and not beds:
        sofa, tv = sofas[0], tvs[0]
        f = front_vector(sofa.pose.rotation_deg)
        fx = sofa.pose.x + f[0] * sofa.product.depth_cm / 2.0
        fy = sofa.pose.y + f[1] * sofa.product.depth_cm / 2.0
        vx, vy = tv.pose.x - fx, tv.pose.y - fy
        d = (vx * vx + vy * vy) ** 0.5 or 1.0
        lateral = abs(vy * f[0] - vx * f[1])
        if (f[0] * vx + f[1] * vy) / d < 0.4:
            return True  # TV not reasonably in front of the sofa
        if lateral > _TV_SOFA_CENTER_TOL_CM:
            return True  # TV centre not aligned with the sofa centre (pushed off by a window / side wall)
        # TV backed onto a WINDOW wall and pushed off-centre by the window: the sofa faces a
        # window and the TV is squeezed beside/below it. A wall without a window is far better.
        tv_f = front_vector(tv.pose.rotation_deg)
        tv_wall = max(analysis.walls, key=lambda w: w.normal[0] * tv_f[0] + w.normal[1] * tv_f[1])
        if lateral > 60.0 and any(o.kind == "window" for o in tv_wall.openings):
            return True
        # A sofa facing across the room's LONGER dimension (sofa on a SHORT wall) leaves a long,
        # half-empty, lopsided room and a far TV. In a clearly rectangular room prefer the sofa on a
        # LONG wall, facing across the SHORT span (the balanced, front-facing arrangement).
        minx, miny, maxx, maxy = analysis.polygon.bounds
        rw, rh = maxx - minx, maxy - miny
        if abs(rw - rh) > 60.0:
            long_axis = (1.0, 0.0) if rw >= rh else (0.0, 1.0)
            if abs(f[0] * long_axis[0] + f[1] * long_axis[1]) > 0.7:
                return True  # sofa faces down the long axis -> lopsided, far TV
    # BEDROOM: a REQUESTED TV must sit DIRECTLY in front of & centred on the BED. A TV rendered off the
    # bed's centre-line (a window / short solid run pushed it off) is never surfaced - MAX penalty, drop
    # the template so the ranking prefers a bed wall that centres the TV (or one that skips it cleanly).
    # Gated on tv_requested, like the sofa block: a TV the user didn't request never drops a template, and
    # a template that SKIPS a requested TV (no `tvs`) isn't dropped either - only one that RENDERS it off.
    beds_for_tv = [p for p in resp.placements if p.category == "bed"]
    if tv_requested and beds_for_tv and tvs:
        bed, tv = beds_for_tv[0], tvs[0]
        bf = front_vector(bed.pose.rotation_deg)  # headboard -> foot (toward the wall the bed faces)
        vx, vy = tv.pose.x - bed.pose.x, tv.pose.y - bed.pose.y
        if bf[0] * vx + bf[1] * vy <= 0.0:
            return True  # TV not in front of the bed (behind the headboard)
        if abs(vy * bf[0] - vx * bf[1]) > _TV_BED_CENTER_TOL_CM:
            return True  # TV centre not aligned with the bed centre -> never render
    if len(sofas) >= 2:
        a = item_polygon(sofas[0].pose.x, sofas[0].pose.y, sofas[0].product.width_cm, sofas[0].product.depth_cm, sofas[0].pose.rotation_deg)
        b = item_polygon(sofas[1].pose.x, sofas[1].pose.y, sofas[1].product.width_cm, sofas[1].product.depth_cm, sofas[1].pose.rotation_deg)
        if a.distance(b) > 130.0:
            return True  # floating, non-adjacent second sofa (not a clean L)
    # A bed jammed against a door swing (not_block_door only stops a >5% overlap, not "too close"):
    # you can't open the door or walk past. Require real clearance, else reject the template.
    beds = [p for p in resp.placements if p.category == "bed"]
    if beds and analysis.swing_arcs:
        b = beds[0]
        bpoly = item_polygon(b.pose.x, b.pose.y, b.product.width_cm, b.product.depth_cm, b.pose.rotation_deg)
        if min(bpoly.distance(arc) for arc in analysis.swing_arcs.values()) < 30.0:
            return True  # bed crammed against the door swing
    # A TV or a sofa that COLLIDES WITH the door swing - intruding on the arc, parked across the
    # door OPENING (the doorway you walk through), or merely FLUSH AGAINST / a sliver into the swing
    # (a sub-5%-overlap or 0 cm touch that slips past validate_item's lenient per-item tolerance) -
    # must never surface. This mirrors the window-wall drop and backstops the BLOCKS_DOOR_SWING error.
    if _furniture_hits_door(resp, analysis):
        return True  # a sofa/tv/side-table/console that collides with (or hugs) a door swing
    if _template_has_overlap(resp):
        return True  # two solid pieces overlap -> never recommend this template
    # "Does this look right?" size backstop: reject a template that still contains a piece clearly
    # bigger than the room warrants for its role - a safety net for the selection size-cap's
    # last-resort fallback (or any future path that skips it). 1.2x the room-proportional max, so
    # only a CLEARLY-oversized piece drops; a slightly-large one is tolerated.
    for p in resp.placements:
        role = placement_group(p.category)
        # A sofa the USER explicitly pinned (Q2 sofa_type != "auto") is honoured by the selector -
        # it relaxes the room-proportional MAX WIDTH for that choice (selector: `store_category is not
        # None and not compact_seating`). So an explicit 3-seater legitimately exceeds this cap; the
        # oversized backstop must NOT then drop the whole template. It still guards the AUTO/fallback
        # sofa (its original purpose) and every non-sofa piece.
        if role == "sofa" and sofa_explicit:
            continue
        cap = expected_max_width(role, analysis.area_cm2)
        if cap is not None and p.product.width_cm > cap * 1.2:
            return True  # a piece too big for the room slipped through
    return False


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


def _tv_in_front(
    resp: AssistLayoutResponse, analysis: RoomAnalysis, tv_requested: bool = True
) -> bool:
    """True only if the TV genuinely sits IN FRONT of the PRIMARY sofa: inside the forward cone
    (facing >= 0.4) AND laterally within the sofa's own width (not shoved diagonally onto a side
    wall). This mirrors the facing+lateral test in _template_issues, so the last-resort fallback
    never surfaces a 'TV off to the side' layout - a TV diagonally in front (facing ~0.6) but past
    the sofa's edge reads as misaligned and must be dropped. The primary is the WIDEST sofa (the
    3-seater); a big-room L-return 2-seater must not be mistaken for it.

    Phase 4: when no TV was REQUESTED the constraint is not applicable - a conversation-focal
    template is always acceptable on this axis - so return True (never filter it out)."""
    if not tv_requested:
        return True
    from spatial_planning.services.spatial.geometry_utils import front_vector
    tvs = [p for p in resp.placements if p.category == "tv_unit"]
    beds = [p for p in resp.placements if p.category == "bed"]
    # BEDROOM: the TV faces the BED, not a sofa. A TV in front of & centred on the bed is a valid
    # front-facing bedroom; a bedroom with no TV placed is acceptable on this axis (the ranking demotes
    # it via _bedroom_tv_bad_wall). Only a TV rendered OFF the bed's centre-line is dropped.
    if beds:
        if not tvs:
            return True
        bed, tv = beds[0], tvs[0]
        bf = front_vector(bed.pose.rotation_deg)
        vx, vy = tv.pose.x - bed.pose.x, tv.pose.y - bed.pose.y
        return (bf[0] * vx + bf[1] * vy) > 0.0 and abs(vy * bf[0] - vx * bf[1]) <= _TV_BED_CENTER_TOL_CM
    sofas = [p for p in resp.placements if p.category == "sofa"]
    if not sofas or not tvs:
        return False  # no sofa+TV pair -> not a valid front-facing living room
    sofa = max(sofas, key=lambda p: p.product.width_cm)
    tv = tvs[0]
    f = front_vector(sofa.pose.rotation_deg)
    fx = sofa.pose.x + f[0] * sofa.product.depth_cm / 2.0
    fy = sofa.pose.y + f[1] * sofa.product.depth_cm / 2.0
    vx, vy = tv.pose.x - fx, tv.pose.y - fy
    d = (vx * vx + vy * vy) ** 0.5 or 1.0
    lateral = abs(vy * f[0] - vx * f[1])
    return (f[0] * vx + f[1] * vy) / d >= 0.4 and lateral <= _TV_SOFA_CENTER_TOL_CM


def _tv_is_clean(resp: AssistLayoutResponse, analysis: RoomAnalysis) -> bool:
    """The TV is placed on a genuinely CLEAR wall - the strict bar for keeping it: SOLID (no window on
    the TV's back wall), at least `TV_DOOR_CLEAR_CM` off every door swing (and never across a door
    opening), AND directly IN FRONT of the sofa (facing + laterally centered). When NO surfaced template
    clears this bar the room has no TV wall, so the engine skips the TV and re-plans conversation-focal
    (see `plan_layout_variants`). Positive predicate; reuses `_tv_in_front` (facing/lateral) and
    `blocked_door_geom` (door opening)."""
    from spatial_planning.services.spatial.geometry_utils import front_vector, item_polygon
    from spatial_planning.services.spatial.validate import blocked_door_geom

    tvs = [p for p in resp.placements if p.category == "tv_unit"]
    sofas = [p for p in resp.placements if p.category == "sofa"]
    if not tvs or not sofas:
        return False
    if not _tv_in_front(resp, analysis, tv_requested=True):
        return False  # not facing / not centered on the sofa
    tv = tvs[0]
    tv_poly = item_polygon(tv.pose.x, tv.pose.y, tv.product.width_cm, tv.product.depth_cm, tv.pose.rotation_deg)
    if blocked_door_geom(analysis, tv.product, tv_poly) is not None:
        return False  # parks across the door opening
    # CRAMMED against the door (the codebase's "in the way of the swing" bar) - not merely short of the
    # ideal 25cm target. A TV ~20cm off the swing opens the door fine and is kept; ~7cm is crammed -> skip.
    if analysis.swing_arcs and min(tv_poly.distance(a) for a in analysis.swing_arcs.values()) < _TEMPLATE_DOOR_CLEAR_CM:
        return False
    tv_f = front_vector(tv.pose.rotation_deg)
    tv_wall = max(analysis.walls, key=lambda w: w.normal[0] * tv_f[0] + w.normal[1] * tv_f[1])
    if any(o.kind == "window" for o in tv_wall.openings):
        return False  # TV on a window wall (glare / can't wall-mount)
    return True


def _palette_swap(
    placement: AssistPlacement,
    style: str | None,
    families: set[str],
    repo: CatalogRepository,
) -> Product | None:
    """A palette-matching replacement for `placement`'s product, or None to keep it as-is.

    The replacement is the SAME store category and its footprint is a SUBSET of the neutral pick's
    (both dims <=, and >= ~55% of its area so it isn't a sliver). A subset centred on an already-valid
    pose can never introduce an overlap / OOB / door / walkway violation, so no re-validation is needed.
    Colour beats style, and a preference never forces a non-existent swap: if the neutral product is
    already on-palette, or nothing in-palette fits within its footprint, we keep the neutral product
    (colour is a preference, never a reason to move or drop a piece). Prefers the LARGEST match, i.e.
    the closest to the neutral size, so the recolour barely changes the footprint."""
    if placement.category == "custom":
        return None
    cur = placement.product
    on_palette = ((not style) or style in (cur.styles or [])) and ((not families) or cur.main_family in families)
    if on_palette:
        return None
    ow, od = cur.width_cm, cur.depth_cm
    min_area = 0.55 * ow * od
    pool = [
        q for q in repo.in_category(placement_group(cur.category))
        if q.category == cur.category
        and q.id != placement.product_id
        and q.width_cm <= ow
        and q.depth_cm <= od
        and q.width_cm * q.depth_cm >= min_area
    ]
    styled = [q for q in pool if style and style in (q.styles or [])]
    colored = [q for q in pool if families and q.main_family in families]
    both = [q for q in styled if q.main_family in families]
    cand = both or colored or styled  # colour beats style; a preference never empties the pool
    if not cand:
        return None
    return max(cand, key=lambda q: (q.width_cm * q.depth_cm, -q.price, q.id))


def _recolor_to_palette(
    neutral: AssistLayoutResponse,
    prefs: Preferences,
    analysis: RoomAnalysis,
) -> AssistLayoutResponse:
    """Re-apply the style/colour palette to a palette-INDEPENDENT layout WITHOUT re-planning it.

    Each placed product is swapped for a palette-matching one of the same store category that fits
    within the neutral pick's footprint, at the SAME pose (see `_palette_swap`). Every swap is a subset
    of an already-validated pose, so the ARRANGEMENT is byte-identical - same walls, same poses, same
    pieces placed - and the palette can never move or DROP furniture. (The old repaint re-ran the recipe
    with palette-filtered products, which selected different-SIZED products that reshaped the seating
    group and dropped opted-in pieces - e.g. the chaise - on some walls but not others: a colour must
    never move the layout.) Only colours change, and only where an in-palette product exists at the
    right size; otherwise the neutral product stays. skipped / findings / notices are unchanged by
    construction (a subset footprint can't alter any fit outcome)."""
    style = prefs.style
    families = set(prefs.color_families or [])
    if not style and not families:
        return neutral
    repo = get_repository()
    new_placements: list[AssistPlacement] = []
    changed = False
    for p in neutral.placements:
        swap = _palette_swap(p, style, families, repo)
        if swap is None:
            new_placements.append(p)
        else:
            new_placements.append(p.model_copy(update={"product_id": swap.id, "product": swap}))
            changed = True
    if not changed:
        return neutral
    total_price = sum(pp.product.price for pp in new_placements if pp.instance_id.startswith(AUTO_PREFIX))
    return neutral.model_copy(
        update={
            "placements": new_placements,
            "proposal_id": _proposal_id(analysis, new_placements),
            "totals": neutral.totals.model_copy(update={"total_price": total_price}),
        }
    )


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

    # Decouple ARRANGEMENT from PALETTE. Generate + rank the wall variants with the style/colour
    # preference STRIPPED, so a rare palette can't swap in odd-sized products that perturb the ranking
    # and flip which wall wins (a Bold/Vibrant rug must never change the sofa wall). The chosen
    # arrangement is thus palette-independent; the palette is re-applied to each surfaced template
    # below (same wall, matching-colour products of comparable size). "Layout first, products second".
    has_palette = bool(preferences.style) or bool(preferences.color_families)
    layout_prefs = prefs.model_copy(update={"style": None, "color_families": []}) if has_palette else prefs

    # Phase 4: whether the user REQUESTED a TV (intent, from the active checklist set). When False
    # the template ranking + drops skip every TV-shaped term (see _template_layout_score /
    # _template_issues / _tv_in_front) so a conversation-focal room is never down-ranked or dropped
    # for an absent TV. True for the default and all goldens -> the TV path is byte-identical.
    has_tv = _tv_requested(prefs, effective_room_type)
    # Did the USER explicitly pick the sofa size (Q2 sofa_type != "auto")? If so the selector honours
    # it and relaxes the room-proportional width cap, so the oversized-piece backstop in
    # _template_issues must exempt that sofa (mirrors the selector's `store_category is not None and
    # not compact_seating`). The compact re-plan sets compact_seating without the user asking, so it
    # is NOT treated as explicit - it stays room-proportional.
    sofa_explicit = prefs.sofa_type != "auto" and not prefs.compact_seating

    primary = _primary_role(recipe) if recipe is not None else None
    if primary is None:  # no single anchor -> one honest layout
        return [("Suggested layout", plan_layout_from_recipe(room, prefs, placed_items, room_type))]

    analysis = analyze_room(room)

    from spatial_planning.services.spatial.geometry_utils import dot as _dot, front_vector as _fv
    _win_walls = {w.wall_index for w in room.windows}
    _door_walls = {d.wall_index for d in room.doors}

    def _bedroom_tv_bad_wall(resp: AssistLayoutResponse) -> int:
        """Bedroom + TV requested: 1 when the TV landed on a WINDOW / DOOR wall (or was skipped), so a
        template with a CLEAN TV wall ranks FIRST ('go for the alternative'). Returns 0 for the living
        room / no-TV, so its template ranking is byte-identical."""
        if effective_room_type != "bedroom" or not has_tv:
            return 0
        tv = next((p for p in resp.placements if placement_group(p.category) == "tv_unit"), None)
        if tv is None:
            return 1  # TV requested but couldn't be placed -> also bad (prefer a template that places it clean)
        tf = _fv(tv.pose.rotation_deg)
        tw = max(range(len(analysis.walls)), key=lambda i: _dot(analysis.walls[i].normal, tf))
        return 1 if tw in (_win_walls | _door_walls) else 0

    def _conversation_focal_fallback(panel: list[tuple[str, AssistLayoutResponse]]):
        # NO CLEAR TV WALL -> skip the TV, re-plan conversation-focal. Keep the TV only when some
        # surfaced template places it on a genuinely CLEAR wall (solid, off the door, facing the sofa -
        # `_tv_is_clean`) WHILE keeping the sofa off the entry (`not _sofa_blocks_entry`): a clean TV
        # bought by parking the sofa on the DOOR wall doesn't count - sofa-off-entry outranks the TV.
        # Otherwise a crammed / misaligned TV is worse than none, so re-run the panel with the TV dropped
        # from the checklist. That flips `_tv_requested` -> False, re-freeing the sofa from its window-
        # avoidance and treating a TV-less room as valid (not degenerate). The recursive call has
        # has_tv=False so it never re-enters. Wraps EVERY living-room return - including the all-broken
        # single-layout fallback below, which otherwise surfaces a crammed/off-centre TV. Living-room only.
        if not (has_tv and effective_room_type == "living_room"):
            return panel
        if any(_tv_is_clean(resp, analysis) and not _sofa_blocks_entry(resp, analysis) for _name, resp in panel):
            return panel
        reduced = sorted(pieces.resolve_active_pieces(preferences.included_pieces) - {"tv_unit"})
        # Strip the palette: this re-plan is an ARRANGEMENT pass and must stay palette-independent (its own
        # inner recolour would run on pre-decision sizes). The outer plan_layout_variants recolours the
        # final result instead.
        no_tv_prefs = preferences.model_copy(update={"included_pieces": reduced, "style": None, "color_families": []})
        pass2 = plan_layout_variants(room, no_tv_prefs, placed_items, room_type, max_variants)
        if not pass2:  # impossible-empty guard - keep the original panel rather than empty it
            return panel
        for _name, resp in pass2:
            _annotate_tv_skipped(resp)
        return pass2

    stats = get_repository().category_stats()
    strategy = resolve_strategy(primary.zone_strategy.name)
    # Phase 4: relax the sofa's window-wall avoidance for candidate-WALL ranking too when no TV was
    # requested, so the best wall (e.g. the solid long wall facing a window) ranks first and becomes
    # the recommended template. Only injected in the no-TV case -> the TV path is byte-identical.
    primary_params = primary.zone_strategy.params
    if not has_tv:
        primary_params = {**primary_params, "tv_requested": False}
    _mode = _side_shift_mode(preferences, effective_room_type)
    if _mode is not None:
        primary_params = {**primary_params, "side_shift_mode": _mode}
    cands = strategy.resolver(primary.categories[0], effective_room_type, analysis, [], stats, primary_params)

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
    # rows carry their wall zone `z` so the palette can be re-applied on that exact wall afterwards.
    good_rows: list[tuple[str, str, AssistLayoutResponse, ZoneData]] = []  # design-sound options
    other_rows: list[tuple[str, str, AssistLayoutResponse, ZoneData]] = []  # weak fallbacks
    seen_ids: set[str] = set()
    for z in distinct[: max_variants + 3]:  # pool extra so we can drop weak walls
        resp = plan_layout_from_recipe(room, layout_prefs, placed_items, room_type, zone_overrides={primary.role: z})
        if category not in {p.category for p in resp.placements}:
            continue  # primary couldn't be placed on this wall - drop the template
        if any(f.severity == "error" for f in resp.findings):
            continue
        if resp.proposal_id in seen_ids:
            continue  # identical arrangement - not a real alternative
        seen_ids.add(resp.proposal_id)
        label, side = _anchor_label(analysis, room, z, piece)
        bucket = good_rows if _template_quality_ok(room, z, category) else other_rows
        bucket.append((label, side, resp, z))

    # rank the design-sound options: COMPLETENESS FIRST, then layout quality. A template that fits ALL the
    # opted-in pieces always ranks above one that drops any, so the RECOMMENDED (first) template is a full
    # layout whenever one exists (e.g. the wall that fits the dining set + chaise beats a "prettier" wall
    # that drops the chaise). Ties (same drop count) fall back to composition score. `_template_issues`
    # still hard-drops genuinely broken templates first, so completeness never promotes a broken layout.
    def _drop_count(resp: AssistLayoutResponse) -> int:
        return sum(1 for sk in resp.skipped if sk.reason == SKIP_DID_NOT_FIT)

    scored = sorted(
        ((_template_layout_score(r[2], analysis, has_tv), r) for r in good_rows),
        key=lambda x: (_bedroom_tv_bad_wall(x[1][2]), _drop_count(x[1][2]), -x[0]),
    )
    kept = [sr for sr in scored if not _template_issues(sr[1][2], analysis, has_tv, sofa_explicit)]
    if not kept:
        # Every design-sound wall has a real issue (e.g. the TV forced onto a window). Prefer a
        # weaker wall that is at least ISSUE-FREE - a sofa under a window with the TV on a CLEAR
        # wall beats a "better" wall whose TV is broken. Never surface a broken layout if a
        # clean one exists anywhere.
        kept = sorted(
            ((_template_layout_score(r[2], analysis, has_tv), r) for r in other_rows if not _template_issues(r[2], analysis, has_tv, sofa_explicit)),
            key=lambda x: (_bedroom_tv_bad_wall(x[1][2]), _drop_count(x[1][2]), -x[0]),
        )
    # NB: we deliberately do NOT pad a single good wall up to two by pulling a weak `other_rows`
    # template. A weak wall means a wall a designer wouldn't offer (a sofa on the DOOR wall, crammed
    # beside the entry) - surfacing it as a second "choice" renders a bad template. One good wall ->
    # one good template. `other_rows` is used ONLY when NO good wall survives (the `if not kept:`
    # branch above), never to fill a thin panel.
    if kept:
        pool = kept
    else:
        # No issue-free template anywhere. Honour "a misaligned template must NEVER render": among
        # ALL flawed options keep only those where the TV is genuinely IN FRONT of the primary sofa
        # (best layout-score first). A flawed-but-aligned template (e.g. TV forced onto a window
        # wall) always beats one where the TV isn't in front of the sofa at all. (No TV requested ->
        # _tv_in_front is vacuously True, so the constraint doesn't filter a conversation-focal room.)
        pool = sorted(
            ((_template_layout_score(r[2], analysis, has_tv), r) for r in (good_rows + other_rows) if _tv_in_front(r[2], analysis, has_tv)),
            key=lambda x: (_bedroom_tv_bad_wall(x[1][2]), _drop_count(x[1][2]), -x[0]),
        )
    rows = [r for _sc, r in pool[:max_variants]]
    # Door/entry safety net - these must NEVER be surfaced, even when the last-resort pool above (which
    # ranks by _tv_in_front only, not the full _template_issues gate) filled `rows`. Three failure modes
    # that can DISAGREE about which template to keep (a door on a short wall forces either the sofa or
    # the TV onto the entry wall), so resolve them by SEVERITY, worst-first, applying each only while it
    # leaves something (the panel is never emptied):
    #   1. hard door block  - a substantial piece OVERLAPS the swing: the door physically can't open.
    #   2. sofa blocks entry - the anchor sits across / beside the walk-in path (you squeeze past it).
    #   3. soft door proximity - a piece within the door's comfort margin, but the door still swings free.
    # Order matters: a soft TV-a-few-cm-off-the-door issue must NOT outrank (and drop) a sofa-on-the-
    # entry-wall template - the reason the door-on-a-short-wall room used to surface the sofa jammed
    # beside the entry.
    for _drop in (_furniture_blocks_door_hard, _sofa_blocks_entry, _furniture_hits_door, _template_has_overlap):
        cleaner = [r for r in rows if not _drop(r[2], analysis)]
        if cleaner:
            rows = cleaner
    # Prefer templates that seat companion seating as a GROUP - an L-return sofa, or an accent chair
    # BESIDE the sofa. Drop a template that is a lone sofa (the chair couldn't flank and was skipped)
    # whenever a grouped alternative exists, so we never surface a lonely single sofa next to a proper
    # conversation group. Kept only if nothing groups a companion (a genuinely constrained room), so
    # the panel is never left empty.
    def _grouped_companion(r: tuple) -> bool:
        pl = r[2].placements
        sfs = [p for p in pl if p.category == "sofa"]
        if len(sfs) >= 2:
            return True  # L-return (its adjacency to the primary is already enforced by _template_issues)
        chs = [p for p in pl if p.category == "accent_chair"]
        if not sfs or not chs:
            return False  # lone sofa - no companion seat
        prim = max(sfs, key=lambda p: p.product.width_cm)
        return min(((c.pose.x - prim.pose.x) ** 2 + (c.pose.y - prim.pose.y) ** 2) ** 0.5 for c in chs) <= 300.0

    grouped_rows = [r for r in rows if _grouped_companion(r)]
    if grouped_rows:
        rows = grouped_rows
    if not rows:  # every option is broken/misaligned - fall back to the single natural layout
        # Plan it palette-INDEPENDENT (layout_prefs); the final recolour pass below repaints it.
        out = _conversation_focal_fallback(
            [(f"{piece} layout", plan_layout_from_recipe(room, layout_prefs, placed_items, room_type))]
        )
    else:
        # unique, readable labels (disambiguate collisions by side), built from the NEUTRAL rows
        out: list[tuple[str, AssistLayoutResponse]] = []
        used: set[str] = set()
        for label, side, resp, _z in rows:
            name = label if label not in used else f"{label} ({side})"
            n = 2
            while name in used:
                name = f"{label} ({side}) {n}"
                n += 1
            used.add(name)
            out.append((name, resp))
        # Arrangement decision (TV-clean / conversation-focal) runs on the palette-INDEPENDENT layout, so
        # a recoloured (narrower) sofa can never flip the "TV in front of the sofa" check and trigger a
        # spurious TV skip.
        out = _conversation_focal_fallback(out)

    # FINAL, purely-cosmetic pass: recolour the finished arrangement IN PLACE (poses fixed). Kept dead
    # last - after EVERY arrangement decision, including the conversation-focal fallback - so no ranking
    # or geometry check ever sees palette-resized products. Each product is swapped for a palette-matching
    # one of the same store category that fits WITHIN the neutral footprint at the same pose (a subset of
    # an already-valid pose), so the palette can never move or drop a piece. See _recolor_to_palette.
    if has_palette:
        out = [(name, _recolor_to_palette(resp, preferences, analysis)) for name, resp in out]
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
