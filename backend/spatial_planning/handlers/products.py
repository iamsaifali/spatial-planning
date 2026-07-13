
from spatial_planning.models.geometry import StrictModel
from spatial_planning.models.products import Product
from spatial_planning.services.catalog import get_repository



class ProductListResponse(StrictModel):
    items: list[Product]
    total: int
    page: int
    page_size: int


def list_products(
    category: str | None = None,
    style: str | None = None,
    color: str | None = None,
    material: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    in_stock: bool | None = None,
    q: str | None = None,
    room_type: str | None = None,
    region: str | None = None,
    luxury_tier: str | None = None,
    sort: str = "relevance",
    page: int = 1,
    page_size: int = 24,
) -> ProductListResponse:
    items, total = get_repository().search(
        category=category,
        style=style,
        color=color,
        material=material,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        q=q,
        room_type=room_type,
        region=region,
        luxury_tier=luxury_tier,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return ProductListResponse(items=items, total=total, page=page, page_size=page_size)


def get_product(product_id: str) -> Product:
    return get_repository().require(product_id, as_request_error=False)
