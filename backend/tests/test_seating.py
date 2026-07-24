"""Phase 2 - living-room seating: seat count (Q1) + main sofa (Q2) + sofa-first fill.

These tests exercise the REAL store catalog (catalog_stores.json), because the small
fixture catalog has no distinct 2-seater / 3-seater / l-shape sofa store categories - it
carries every sofa as the generic "sofa" category, so Q2 pinning can only be observed
against the real multi-store catalog. The gap-driven ladder + hard combo rule are also
swept here across many rooms / seat counts / sofa types.

Catalog note: `l-shape-sofa` products in catalog_stores.json are all tagged
room_types=["majlis"], so a living-room l-shape request is catalog-UNAVAILABLE and
gracefully sizes DOWN to a 3-seater with a notice (honour-then-size-down) rather than
shipping a broken layout - asserted below.

Seat-capacity note: the store catalog infers a sofa's seating_capacity from its WIDTH, so a
"2-seater-sofa" (~200 cm) actually seats 3. The tests therefore assert the sofa-first
LADDER property (chairs stay 0 until the sofa group can't reach the target, then top up
capped at 2) computed from the live seat counts, not hard-coded seat arithmetic.
"""

import pytest

from spatial_planning.config import get_settings
from spatial_planning.models.geometry import Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.services.catalog import CatalogRepository, set_repository
from spatial_planning.services.recommend.orchestrator import plan_layout_from_recipe

STORE_CATALOG = "spatial_planning/data/catalog_stores.json"
FIXTURE_CATALOG = "spatial_planning/data/catalog.json"


@pytest.fixture()
def store_repo():
    """Load the real multi-store catalog (distinct 2-/3-seater / l-shape sofa categories),
    restoring the fixture catalog afterwards so other tests stay on the deterministic seed."""
    settings = get_settings()
    repo = CatalogRepository.load(settings.resolve(STORE_CATALOG), settings.resolve(settings.static_dir))
    set_repository(repo)
    yield repo
    set_repository(CatalogRepository.load(settings.resolve(FIXTURE_CATALOG), settings.resolve(settings.static_dir)))


def _square(w: float, h: float, door_w: float = 90) -> Room:
    return Room.model_validate(
        {
            "vertices": [[0, 0], [w, 0], [w, h], [0, h]],
            "doors": [{"id": "d", "wall_index": 0, "offset_cm": 40, "width_cm": door_w}],
            "windows": [],
        }
    )


def _plan(room: Room, **pref_kwargs):
    return plan_layout_from_recipe(room, Preferences(**pref_kwargs), [])


def _sofa_cats(resp) -> list[str]:
    return [p.product.category for p in resp.placements if p.category == "sofa"]


def _chairs(resp) -> int:
    return sum(1 for p in resp.placements if p.category == "accent_chair")


def _seated(resp) -> int:
    return sum(p.product.seating_capacity for p in resp.placements if p.product.seating_capacity > 0)


def _no_hard_errors(resp) -> bool:
    return not [f for f in resp.findings if f.severity == "error"]


# --- Q2: the sofa_type choice pins the PRIMARY sofa -------------------------------


def test_sofa_type_pins_2_seater(store_repo):
    resp = _plan(_square(700, 600), sofa_type="2-seater")
    assert _sofa_cats(resp)[0] == "2-seater-sofa"
    assert _no_hard_errors(resp)


def test_sofa_type_pins_3_seater(store_repo):
    resp = _plan(_square(700, 600), sofa_type="3-seater")
    assert _sofa_cats(resp)[0] == "3-seater-sofa"
    assert _no_hard_errors(resp)


def test_sofa_type_auto_matches_area_default(store_repo):
    """auto reproduces today's area-based default: a small/medium room gets a 2-seater
    primary, a large room a 3-seater (no explicit count)."""
    small = _plan(_square(320, 300), sofa_type="auto")
    large = _plan(_square(700, 600), sofa_type="auto")
    assert _sofa_cats(small)[0] == "2-seater-sofa"
    assert _sofa_cats(large)[0] == "3-seater-sofa"


def test_lshape_unavailable_for_living_room_sizes_down_with_notice(store_repo):
    """l-shape-sofa is catalog-unavailable for living rooms (majlis-tagged), so an explicit
    l-shape request honours-then-sizes-down to a 3-seater and surfaces a notice - never a
    broken/absent sofa."""
    resp = _plan(_square(700, 600), sofa_type="l-shape")
    assert _sofa_cats(resp)  # a sofa WAS placed
    assert _sofa_cats(resp)[0] != "l-shape-sofa"  # sized down (l-shape is majlis-only here)
    assert any("wouldn't fit this room comfortably" in n for n in resp.notices)
    assert _no_hard_errors(resp)


# --- Q2: honour-then-size-down when the chosen sofa can't be placed ---------------


def test_honour_then_size_down_genuine_nonfit_3_seater(store_repo):
    """A GENUINELY too-short wall (no 3-seater physically fits) + an explicit 3-seater falls
    back DOWN the ladder to a fitting sofa and appends a size-down notice (never leaves the room
    sofa-less). This is the honour-then-size-down ladder - a real physical non-fit, distinct from
    the compact two-pass."""
    resp = _plan(_square(180, 180), sofa_type="3-seater")
    assert _sofa_cats(resp)  # a sofa was still placed
    assert _sofa_cats(resp)[0] != "3-seater-sofa"  # sized down to what fits
    assert any("3-seater" in n and "wouldn't fit" in n for n in resp.notices)
    assert _no_hard_errors(resp)


def test_explicit_3_seater_honoured_as_lone_when_wall_fits(store_repo):
    """The bug fix: a user who EXPLICITLY picks a 3-seater in a room whose wall physically holds
    one (480x360, 17.3 m2 - the 4.80 m wall easily fits a ~2.1 m 3-seater) gets a LONE 3-seater,
    even though the room can't ALSO fit an L-return. The "never a lone 3-seater" compact two-pass
    is AUTO-only, so an explicit pick is honoured - no downgrade, no misleading "wouldn't fit" notice.
    The same room on AUTO still resolves to a 2-seater (area-based default / never-lone intact)."""
    resp = _plan(_square(480, 360), sofa_type="3-seater")
    assert _sofa_cats(resp) == ["3-seater-sofa"]  # a single, lone 3-seater - honoured, not compacted
    assert not any("wouldn't fit" in n for n in resp.notices)  # NOT the misleading non-fit message
    assert _no_hard_errors(resp)

    auto = _plan(_square(480, 360), sofa_type="auto")
    assert _sofa_cats(auto)[0] == "2-seater-sofa"  # AUTO unchanged: small/medium -> 2-seater


# --- Q1: seat count drives the sofa-first fill ladder -----------------------------


def test_gap_driven_chairs_are_the_last_resort(store_repo):
    """Chairs stay 0 while the sofa group (primary + L-return) still meets the target, and an
    odd +1 tops up with exactly one chair (capped at 2). This is the sofa-first ladder."""
    room = _square(550, 450)  # fits a 3-seater + an L-return
    # a target the sofa group already meets -> no chair
    low = _plan(room, seating_capacity=4)
    assert _chairs(low) == 0
    assert len(_sofa_cats(low)) == 2  # 3-seater + L-return, no chair
    sofa_seats = _seated(low)
    assert sofa_seats >= 4

    # exactly at the sofa-group capacity -> still zero chairs
    at = _plan(room, seating_capacity=sofa_seats)
    assert _chairs(at) == 0
    assert _seated(at) == sofa_seats

    # one over the sofa-group capacity -> exactly one chair tops it up (still gap-driven, <= 2)
    over = _plan(room, seating_capacity=sofa_seats + 1)
    assert _chairs(over) == 1
    assert _seated(over) == sofa_seats + 1
    assert _no_hard_errors(over)


def test_gap_driven_chairs_never_exceed_two(store_repo):
    room = _square(600, 500)
    resp = _plan(room, seating_capacity=20)  # ask for far more than the room can seat
    assert _chairs(resp) <= 2


# --- Hard combo rule: never a lone 3-seater / 3-seater + lone chair ---------------


def test_hard_combo_rule_holds_across_sweep(store_repo):
    """Across a sweep of rooms x seat counts, the AUTO sofa path NEVER resolves to a lone
    3-seater (with or without chairs). It is always (3-seater + L-return) or a 2-seater
    primary - the compact two-pass guarantees this. The never-lone rule is AUTO-only: an
    EXPLICIT pick (sofa_type != "auto") is honoured, so a lone 3-seater there is allowed."""
    violations = []
    for w in (320, 420, 520, 620, 720):
        for h in (280, 360, 460, 560):
            room = _square(w, h)
            for cap in (None, 2, 4, 6, 8, 10):
                resp = plan_layout_from_recipe(
                    room, Preferences(sofa_type="auto", seating_capacity=cap), []
                )
                sofas = _sofa_cats(resp)
                # a lone 3-seater / l-shape (single sofa) is the forbidden combo for AUTO
                if len(sofas) == 1 and sofas[0] in ("3-seater-sofa", "l-shape-sofa"):
                    violations.append((w, h, cap, sofas, _chairs(resp)))
    assert violations == [], f"lone-3-seater combos (auto): {violations[:5]}"


def test_safety_sweep_no_hard_geometry_findings(store_repo):
    """No layout in the sweep blocks a door / walkway, overlaps, or leaves the room."""
    bad_codes = {"OVERLAP_ITEM", "OUT_OF_BOUNDS", "BLOCKS_DOOR_SWING", "BLOCKS_WALKWAY"}
    offenders = []
    for w in (340, 480, 620):
        for h in (300, 420, 540):
            room = _square(w, h)
            for sofa_type in ("auto", "2-seater", "3-seater", "l-shape"):
                for cap in (None, 3, 6, 9):
                    resp = plan_layout_from_recipe(
                        room, Preferences(sofa_type=sofa_type, seating_capacity=cap), []
                    )
                    hits = [f.code for f in resp.findings if f.code in bad_codes]
                    if hits:
                        offenders.append((w, h, sofa_type, cap, hits))
    assert offenders == [], f"geometry violations: {offenders[:5]}"


# --- Q1: seat count rounds UP, and messages when it can't be reached --------------


def test_cannot_reach_target_seats_fewer_with_notice(store_repo):
    """A tiny room asked for 8 seats seats as many as fit and says how many it comfortably
    seats (seat count rounds up, never over-fills the room)."""
    resp = _plan(_square(320, 300), seating_capacity=8)
    seated = _seated(resp)
    assert 0 < seated < 8
    assert any(n == f"This room comfortably seats {seated}." for n in resp.notices)
    assert _no_hard_errors(resp)


def _large_no_lreturn_room() -> Room:
    """A large room (820x300 = 24.6 m2 -> AUTO would pick a 3-seater) whose short walls carry
    windows, so no L-return can be placed. AUTO thus produces a lone 3-seater on the first pass
    and the compact two-pass fires."""
    return Room.model_validate(
        {
            "vertices": [[0, 0], [820, 0], [820, 300], [0, 300]],
            "doors": [{"id": "d", "wall_index": 0, "offset_cm": 680, "width_cm": 90}],
            "windows": [
                {"id": "w1", "wall_index": 1, "offset_cm": 50, "width_cm": 200},
                {"id": "w2", "wall_index": 3, "offset_cm": 50, "width_cm": 200},
            ],
        }
    )


def test_compact_two_pass_still_fires_for_auto(store_repo):
    """AUTO in a large room (>=24 m2, so the raw default is a 3-seater) that can't get an L-return
    re-plans as a compact 2-seater - never a lone 3-seater. The never-lone compact two-pass is
    fully preserved for the AUTO path."""
    resp = plan_layout_from_recipe(_large_no_lreturn_room(), Preferences(sofa_type="auto"), [])
    sofas = _sofa_cats(resp)
    assert len(sofas) == 1
    assert sofas[0] == "2-seater-sofa"  # compact re-plan replaced the lone 3-seater
    assert _no_hard_errors(resp)


def test_explicit_3_seater_not_compacted_in_lone_room(store_repo):
    """In the SAME large no-L-return room, an EXPLICIT 3-seater is honoured as a lone 3-seater
    (the compact two-pass does NOT fire for an explicit pick), while AUTO still compacts to a
    2-seater. This is the crux of the fix: the never-lone rule is AUTO-only."""
    room = _large_no_lreturn_room()
    explicit = plan_layout_from_recipe(room, Preferences(sofa_type="3-seater"), [])
    assert _sofa_cats(explicit) == ["3-seater-sofa"]  # lone 3-seater, not compacted
    assert not any("wouldn't fit" in n for n in explicit.notices)
    assert _no_hard_errors(explicit)

    auto = plan_layout_from_recipe(room, Preferences(sofa_type="auto"), [])
    assert _sofa_cats(auto) == ["2-seater-sofa"]  # auto still compacts (never-lone intact)
