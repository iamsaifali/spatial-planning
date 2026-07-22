"""Phase 0 (Contracts) — data-contract additions for the living-room checklist.

These assert the ADDITIVE, non-behavioural contracts only: the new optional Preferences
fields, the pieces.py single-source-of-truth table, and the AssistLayoutResponse.notices
channel. None of this is wired into the planner yet.
"""

from spatial_planning.models.api import (
    SKIP_DID_NOT_FIT,
    SKIP_NOT_INCLUDED,
    AssistLayoutResponse,
    AssistTotals,
)
from spatial_planning.models.preferences import Preferences
from spatial_planning.services.recipe import pieces


# --- Preferences: new optional fields, backward compatible --------------------------

def test_preferences_defaults_unchanged():
    p = Preferences()
    assert p.included_pieces is None
    assert p.sofa_type == "auto"


def test_preferences_accepts_checklist_intent():
    p = Preferences(included_pieces=["rug", "console"], sofa_type="l-shape")
    assert p.included_pieces == ["rug", "console"]
    assert p.sofa_type == "l-shape"


def test_preferences_sofa_type_accepts_all_choices():
    for choice in ("auto", "2-seater", "3-seater", "l-shape"):
        assert Preferences(sofa_type=choice).sofa_type == choice


# --- pieces.py: the single source of truth ------------------------------------------

EXPECTED_CHECKLIST = {
    "rug", "coffee_table", "tv_unit", "floor_lamp",
    "chaise_lounge", "dining_set", "side_table", "console", "plant", "vases",
}
EXPECTED_ESSENTIALS = {"rug", "coffee_table", "tv_unit", "floor_lamp"}


def test_checklist_keys_are_canonical():
    assert set(pieces.checklist_keys()) == EXPECTED_CHECKLIST
    assert len(pieces.checklist_keys()) == 10  # no duplicates
    # core pieces are NOT valid checklist entries
    assert "sofa" not in pieces.checklist_keys()
    assert "accent_chair" not in pieces.checklist_keys()


def test_every_checklist_key_resolves():
    for key in pieces.checklist_keys():
        p = pieces.piece(key)
        assert p is not None
        assert p.key == key
        assert p.tier in ("essential", "optional")
        assert p.store_category  # non-empty reference category


def test_essentials_set():
    essentials = {k for k in pieces.checklist_keys() if pieces.is_essential(k)}
    assert essentials == EXPECTED_ESSENTIALS


def test_priority_ranks_unique_and_cover_1_to_11():
    # The numbered drop-priority order = sofa (core anchor) + the 10 checklist keys.
    ranked = ["sofa", *pieces.checklist_keys()]
    ranks = [pieces.priority_of(k) for k in ranked]
    assert None not in ranks
    assert len(set(ranks)) == 11
    assert set(ranks) == set(range(1, 12))
    # spot-check the spec ordering
    assert pieces.priority_of("sofa") == 1
    assert pieces.priority_of("rug") == 2
    assert pieces.priority_of("vases") == 11


def test_core_pieces_recorded():
    for key in ("sofa", "accent_chair"):
        p = pieces.piece(key)
        assert p is not None
        assert p.tier == "core"


def test_piece_for_role_lookup():
    assert pieces.piece_for_role("floor_anchor").key == "rug"
    assert pieces.piece_for_role("focal_media").key == "tv_unit"
    assert pieces.piece_for_role("storage").key == "console"
    # roles that don't map to any piece
    assert pieces.piece_for_role("nonexistent_role") is None


def test_role_none_for_phase3_pieces():
    # chaise_lounge (Phase 3a) and dining_set (Phase 3b) now both own recipe roles.
    assert pieces.piece("chaise_lounge").role == "lounge_chaise"
    # dining_set gates a GROUP: the dining table role plus the dining chairs role (extra_roles).
    assert pieces.piece("dining_set").role == "dining_table"
    assert pieces.piece("dining_set").extra_roles == ("dining_seating",)


def test_dining_group_roles_map_to_one_piece():
    # BOTH dining roles resolve back to the single dining_set checklist key, so the opt-in
    # gates the table AND the chairs together (neither is an always-run "core" role).
    assert pieces.piece_for_role("dining_table").key == "dining_set"
    assert pieces.piece_for_role("dining_seating").key == "dining_set"


def test_unknown_key_returns_none():
    assert pieces.piece("nope") is None
    assert pieces.priority_of("nope") is None
    assert pieces.is_essential("nope") is False


# --- AssistLayoutResponse.notices + skip reason constants ----------------------------

def test_response_notices_empty_by_default():
    resp = AssistLayoutResponse(
        proposal_id="lay_test",
        totals=AssistTotals(item_count=0, total_price=0, currency="USD"),
    )
    assert resp.notices == []


def test_planner_intent_skip_reason_constants():
    assert SKIP_NOT_INCLUDED == "not_included"
    assert SKIP_DID_NOT_FIT == "did_not_fit"
