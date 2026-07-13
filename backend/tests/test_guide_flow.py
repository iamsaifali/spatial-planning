import pytest

from spatial_planning.errors import AppError
from spatial_planning.models.geometry import PlacedItem
from spatial_planning.services.guide.flow import completeness_pct, missing_essentials, require_step, steps_with_status


def _placed(catalog_repo, category, iid):
    product = catalog_repo.in_category(category)[0]
    return (PlacedItem(instance_id=iid, product_id=product.id, x=100, y=100), product)


def test_steps_initial_state():
    infos = steps_with_status([])
    assert len(infos) == 9
    assert infos[0].key == "sofa" and infos[0].status == "current"
    assert all(i.status == "pending" for i in infos[1:])


def test_steps_progress(catalog_repo):
    placed = [_placed(catalog_repo, "sofa", "a")]
    infos = steps_with_status(placed)
    assert infos[0].status == "done"
    assert infos[1].status == "current"


def test_completeness(catalog_repo):
    assert completeness_pct([]) == 0
    placed = [_placed(catalog_repo, "sofa", "a"), _placed(catalog_repo, "rug", "b")]
    assert completeness_pct(placed) == 40
    missing = [cat for cat, _ in missing_essentials(placed)]
    assert "tv_unit" in missing and "sofa" not in missing


def test_unknown_step():
    with pytest.raises(AppError):
        require_step("bathtub")
