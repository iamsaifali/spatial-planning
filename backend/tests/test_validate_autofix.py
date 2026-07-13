from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.validation import (
    BLOCKS_DOOR_SWING,
    MUST_FIX_CODES,
    OUT_OF_BOUNDS,
    OVERLAP_ITEM,
)
from spatial_planning.services.spatial.analyze import analyze_room
from spatial_planning.services.spatial.autofix import find_autofix, find_better_placement
from spatial_planning.services.spatial.validate import validate_item


def _sofa(catalog_repo):
    return catalog_repo.in_category("sofa")[0]


def _item(product, x, y, rot=0.0, iid="i1"):
    return PlacedItem(instance_id=iid, product_id=product.id, x=x, y=y, rotation_deg=rot)


def test_clean_placement_has_no_errors(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    product = _sofa(catalog_repo)
    # against the bottom wall, centered, facing up
    item = _item(product, 240, 360 - product.depth_cm / 2 - 4, 180)
    findings = validate_item(analysis, [], item, product)
    assert not [f for f in findings if f.severity == "error"]


def test_out_of_bounds_detected(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    product = _sofa(catalog_repo)
    item = _item(product, 470, 180, 0)  # mostly outside the right wall
    findings = validate_item(analysis, [], item, product)
    assert any(f.code == OUT_OF_BOUNDS for f in findings)


def test_overlap_detected(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    product = _sofa(catalog_repo)
    a = _item(product, 240, 180, 0, "a")
    b = _item(product, 250, 190, 0, "b")
    findings = validate_item(analysis, [(a, product)], b, product)
    assert any(f.code == OVERLAP_ITEM for f in findings)


def test_door_swing_detected(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    product = _sofa(catalog_repo)
    item = _item(product, 85, 50, 0)  # right on top of the door arc
    findings = validate_item(analysis, [], item, product)
    assert any(f.code == BLOCKS_DOOR_SWING for f in findings)


def test_rug_exempt_from_overlap(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    sofa = _sofa(catalog_repo)
    rug = catalog_repo.in_category("rug")[0]
    sofa_item = _item(sofa, 240, 300, 180, "s")
    rug_item = _item(rug, 240, 250, 180, "r")
    findings = validate_item(analysis, [(sofa_item, sofa)], rug_item, rug)
    assert not [f for f in findings if f.code == OVERLAP_ITEM]


def test_autofix_resolves_bad_poses(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    product = _sofa(catalog_repo)
    stats = catalog_repo.category_stats()
    bad_poses = [
        (470, 180, 0), (85, 50, 0), (10, 10, 45), (240, -20, 0),
        (460, 350, 90), (60, 60, 0), (470, 40, 0), (240, 370, 180),
    ]
    for x, y, rot in bad_poses:
        item = _item(product, x, y, rot, f"bad-{x}-{y}")
        findings = validate_item(analysis, [], item, product)
        must_fix = [f for f in findings if f.code in MUST_FIX_CODES]
        if not must_fix:
            continue
        fix = find_autofix(analysis, [], item, product, findings)
        better = find_better_placement(analysis, [], item, product, stats)
        assert fix is not None or better is not None, f"no fix found for pose {(x, y, rot)}"
        if fix is not None:
            fixed_item = _item(product, fix.pose.x, fix.pose.y, fix.pose.rotation_deg, "fx")
            fixed_findings = validate_item(analysis, [], fixed_item, product)
            assert not [f for f in fixed_findings if f.code in MUST_FIX_CODES and f.code != "BLOCKS_WALKWAY"]


def test_autofix_deterministic(rect_room, catalog_repo):
    analysis = analyze_room(rect_room)
    product = _sofa(catalog_repo)
    item = _item(product, 470, 180, 0)
    findings = validate_item(analysis, [], item, product)
    fix1 = find_autofix(analysis, [], item, product, findings)
    fix2 = find_autofix(analysis, [], item, product, findings)
    assert fix1 == fix2
