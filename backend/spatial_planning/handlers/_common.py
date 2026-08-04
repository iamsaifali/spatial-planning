"""Shared request helpers for routers."""

from spatial_planning.errors import DUPLICATE_INSTANCE, AppError
from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.products import Product
from spatial_planning.services.catalog import get_repository
from spatial_planning.services.spatial.core import WallData

PlacedProduct = tuple[PlacedItem, Product]


def _pseudo_product(item: PlacedItem) -> Product:
    """A user's own kept item: occupies space, costs nothing, never recommended."""
    spec = item.custom
    assert spec is not None
    return Product(
        id=item.product_id,
        name=spec.name,
        category="custom",
        price=0,
        width_cm=spec.width_cm,
        depth_cm=spec.depth_cm,
        height_cm=spec.height_cm,
        style_tags=[],
        colors=[],
        image_url="",
        is_walkable=False,
    )


def resolve_item(item: PlacedItem) -> Product:
    """Product for a placed item: catalog lookup, or a pseudo-product for kept items."""
    if item.custom is not None:
        return _pseudo_product(item)
    return get_repository().require(item.product_id)


def resolve_placed(placed_items: list[PlacedItem]) -> list[PlacedProduct]:
    """Validate instance ids + product ids and pair items with products."""
    seen: set[str] = set()
    out: list[PlacedProduct] = []
    for item in placed_items:
        if item.instance_id in seen:
            raise AppError(
                code=DUPLICATE_INSTANCE,
                message=f"Duplicate instance_id '{item.instance_id}'.",
                status_code=422,
            )
        seen.add(item.instance_id)
        out.append((item, resolve_item(item)))
    return out


def wall_label(wall: WallData) -> str:
    nx, ny = wall.normal
    if ny > 0.7:
        return "top"
    if ny < -0.7:
        return "bottom"
    if nx > 0.7:
        return "left"
    if nx < -0.7:
        return "right"
    return "angled"
