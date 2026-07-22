"""Phase 4 — TV-unchecked -> conversation-focal living-room layout.

When the user UNCHECKS the TV (`included_pieces` omitting `tv_unit`), two bits of logic that
assume a TV always exists must RELAX so the room becomes conversation-focal:

  1. `_sofa_zones` drops its -0.7 "faces a window wall" penalty (it exists only to reserve a
     clear wall for the TV), so the sofa takes the genuinely best wall - even facing a window.
  2. The template ranking + drops skip every TV-shaped term (TV-in-front reward, viewing
     distance, TV-centred penalty, and the drops for "TV not in front" / "past the sofa edge" /
     "on a window wall"). A no-TV layout is never dropped or down-ranked for an absent TV.

The signal is INTENT (was `tv_unit` REQUESTED), not "was a TV placed": derived from the active
checklist set (`included_pieces` if given, else the essentials default which INCLUDES `tv_unit`).

Invariant: whenever a TV IS requested (the default and every golden), behaviour is byte-identical.
"""

import pytest

from spatial_planning.models.geometry import Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.recommend.orchestrator import (
    _template_layout_score,
    _template_issues,
    _tv_in_front,
    _tv_requested,
    plan_assist_templates,
    plan_layout_from_recipe,
)

# Codes the validation gate must NEVER let through (safety spot-check).
UNSAFE_CODES = {"OVERLAP_ITEM", "OUT_OF_BOUNDS", "BLOCKS_DOOR_SWING", "BLOCKS_WALKWAY"}

# The essentials-only default golden (TV included) — must reproduce byte-identically.
GOLDEN_DEFAULT_PID = "lay_7ab3d93548"

# The essentials checklist WITHOUT the TV (rug + coffee table + floor lamp) — TV unchecked.
NO_TV = ["rug", "coffee_table", "floor_lamp"]

# 480x360 room, door on wall 0, window on wall 2 — the essentials-default golden room.
LIVING_ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 90, "swing": "inward", "hinge": "left"}],
    "windows": [{"id": "w1", "wall_index": 2, "offset_cm": 140, "width_cm": 180}],
    "wall_height_cm": 270,
}

# The FLIP room: the genuinely best wall (the solid, entry-clear LONG wall 0 at the bottom) FACES a
# window on wall 2. WITH a TV, the sofa is pushed OFF wall 0 onto the top window wall (to keep the TV
# off the glass). WITHOUT a TV, the -0.7 penalty vanishes so the sofa takes the best wall 0 (bottom),
# facing the room/window — the relaxation actually firing.
FLIP_ROOM = {
    "vertices": [[0, 0], [480, 0], [480, 360], [0, 360]],
    "doors": [{"id": "d", "wall_index": 3, "offset_cm": 40, "width_cm": 85}],
    "windows": [{"id": "w", "wall_index": 2, "offset_cm": 150, "width_cm": 180}],
    "wall_height_cm": 270,
}

# A big room that yields an L-return (2 sofas) — used to prove the non-TV ranking terms still fire.
BIG_LIVING = {
    "vertices": [[0, 0], [600, 0], [600, 520], [0, 520]],
    "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 40, "width_cm": 85}],
    "windows": [],
    "wall_height_cm": 270,
}

# Safety-sweep rooms (varied shapes / door + window placements), all living-room.
SWEEP_ROOMS = {
    "golden": LIVING_ROOM,
    "flip": FLIP_ROOM,
    "big": BIG_LIVING,
    "windows_both_long_walls": {
        "vertices": [[0, 0], [520, 0], [520, 400], [0, 400]],
        "doors": [{"id": "d", "wall_index": 1, "offset_cm": 120, "width_cm": 90}],
        "windows": [
            {"id": "w1", "wall_index": 0, "offset_cm": 160, "width_cm": 200},
            {"id": "w2", "wall_index": 2, "offset_cm": 160, "width_cm": 200},
        ],
    },
    "narrow": {
        "vertices": [[0, 0], [560, 0], [560, 300], [0, 300]],
        "doors": [{"id": "d", "wall_index": 3, "offset_cm": 60, "width_cm": 85}],
        "windows": [{"id": "w", "wall_index": 0, "offset_cm": 220, "width_cm": 160}],
    },
    "L_shape": {
        "vertices": [[0, 0], [600, 0], [600, 300], [300, 300], [300, 480], [0, 480]],
        "doors": [{"id": "d1", "wall_index": 0, "offset_cm": 60, "width_cm": 90}],
        "windows": [{"id": "w1", "wall_index": 5, "offset_cm": 100, "width_cm": 160}],
    },
}


def _room(spec):
    return Room.model_validate(spec)


def _prefs(pieces=None):
    return Preferences(styles=["modern"], included_pieces=pieces)


def _sofa(resp):
    return next(p for p in resp.placements if p.category == "sofa")


def _cats(resp):
    return {p.category for p in resp.placements}


def _unsafe(resp):
    return [f for f in resp.findings if f.code in UNSAFE_CODES]


# --- 1. TV unchecked -> no TV placed, sofa on a sensible wall, layout valid --------------


def test_no_tv_omits_tv_and_places_valid_sofa(catalog_repo):
    resp = plan_layout_from_recipe(_room(FLIP_ROOM), _prefs(NO_TV), [])
    assert "tv_unit" not in _cats(resp)  # TV was unchecked -> never placed
    assert "sofa" in _cats(resp)  # core seating still placed
    # The sofa now sits on the best wall — the solid, entry-clear bottom wall (wall 0, y<180) it
    # would previously have been PENALISED for taking (it faces the window on wall 2).
    assert _sofa(resp).pose.y < 180
    # valid — no error findings anywhere, no unsafe placement
    assert not [f for f in resp.findings if f.severity == "error"]
    assert not _unsafe(resp)


# --- 2. The relaxation actually fires: with a TV the sofa avoids the window wall; without it,
#        it takes that wall ---------------------------------------------------------------


def test_relaxation_flips_sofa_wall_between_tv_and_no_tv(catalog_repo):
    room = _room(FLIP_ROOM)
    with_tv = plan_layout_from_recipe(room, _prefs(["rug", "coffee_table", "tv_unit", "floor_lamp"]), [])
    no_tv = plan_layout_from_recipe(room, _prefs(NO_TV), [])

    assert "tv_unit" in _cats(with_tv)
    assert "tv_unit" not in _cats(no_tv)

    # WITH a TV: the sofa is pushed onto the TOP window wall (wall 2, y>180) to reserve the clear
    # bottom wall for the TV. WITHOUT a TV: the sofa takes the best BOTTOM wall (wall 0, y<180).
    assert _sofa(with_tv).pose.y > 180  # contorted onto the window wall to keep the TV off glass
    assert _sofa(no_tv).pose.y < 180  # conversation-focal: the genuinely best wall
    assert _sofa(with_tv).pose.y != _sofa(no_tv).pose.y  # the relaxation moved the sofa


# --- 3. TV included (the default) is UNCHANGED — byte-identical golden --------------------


def test_default_tv_included_is_byte_identical(catalog_repo):
    # included_pieces=None -> essentials default INCLUDES tv_unit -> no relaxation.
    resp = plan_layout_from_recipe(_room(LIVING_ROOM), _prefs(None), [])
    assert "tv_unit" in _cats(resp)
    assert resp.proposal_id == GOLDEN_DEFAULT_PID  # strict no-op when a TV is requested


def test_tv_requested_signal_is_intent_not_placement(catalog_repo):
    # The signal derives from the active checklist set, not from what was placed.
    assert _tv_requested(_prefs(None), "living_room") is True  # essentials default includes the TV
    assert _tv_requested(_prefs(["rug", "coffee_table", "tv_unit"]), "living_room") is True
    assert _tv_requested(_prefs(NO_TV), "living_room") is False  # omits tv_unit -> conversation-focal
    # Non-living rooms and the legacy path are always "requested" (feature is living-room only).
    assert _tv_requested(_prefs(NO_TV), "bedroom") is True


# --- 4. A no-TV layout is never dropped or down-ranked for TV reasons ---------------------


def test_no_tv_layout_not_dropped_for_tv_reasons(catalog_repo):
    room = _room(FLIP_ROOM)
    analysis = analyze_room(room)
    resp = plan_layout_from_recipe(room, _prefs(NO_TV), [])

    # The "TV genuinely in front of the sofa" gate is vacuously satisfied when no TV was requested
    # (it must never filter a conversation-focal template), but WOULD reject this TV-less layout if a
    # TV were expected.
    assert _tv_in_front(resp, analysis, tv_requested=False) is True
    assert _tv_in_front(resp, analysis, tv_requested=True) is False

    # A no-TV layout facing a window is NOT a template issue (the TV-on-window / TV-not-in-front
    # drops are gated off); it would only be an issue if a TV were expected there.
    assert _template_issues(resp, analysis, tv_requested=False) is False

    # End-to-end: the template panel surfaces the sofa on the (previously TV-dropped) best wall,
    # rather than collapsing to a single fallback — and it never contains a TV.
    templates = plan_assist_templates(room, _prefs(NO_TV), [])
    assert templates
    _lbl, recommended, top = templates[0]
    assert recommended is True
    assert "tv_unit" not in _cats(top)
    assert _sofa(top).pose.y < 180  # the recommended template took the relaxed best wall


def test_no_tv_ranking_terms_still_fire(catalog_repo):
    # With no TV, the TV terms are skipped but the TV-INDEPENDENT terms (tight L-return, chair
    # proximity, warnings) must still rank walls. A big-room no-TV layout with an L-return scores
    # POSITIVE on the L-return reward when tv_requested=False, whereas the old degenerate path
    # (tv_requested=True but no TV placed) returns a flat 0.0 for every template.
    room = _room(BIG_LIVING)
    analysis = analyze_room(room)
    resp = plan_layout_from_recipe(room, _prefs(NO_TV), [])
    assert len([p for p in resp.placements if p.category == "sofa"]) >= 2  # L-return formed
    assert _template_layout_score(resp, analysis, tv_requested=False) > 0.0  # non-TV terms rank it
    assert _template_layout_score(resp, analysis, tv_requested=True) == 0.0  # degenerate w/o a TV


# --- 5. Safety holds across a no-TV room sweep -------------------------------------------


def test_no_tv_safety_sweep(catalog_repo):
    checked = 0
    for name, spec in SWEEP_ROOMS.items():
        resp = plan_layout_from_recipe(_room(spec), _prefs(NO_TV), [])
        assert "tv_unit" not in _cats(resp), name
        assert not _unsafe(resp), f"{name}: {[f.code for f in _unsafe(resp)]}"
        assert not [f for f in resp.findings if f.severity == "error"], name
        checked += 1
    assert checked == len(SWEEP_ROOMS)
