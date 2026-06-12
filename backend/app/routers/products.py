from fastapi import APIRouter, Query

from app.models.geometry import StrictModel
from app.models.products import Product
from app.services.catalog import get_repository

router = APIRouter(prefix="/products", tags=["products"])


class ProductListResponse(StrictModel):
    items: list[Product]
    total: int
    page: int
    page_size: int


@router.get("", response_model=ProductListResponse)
def list_products(
    category: str | None = None,
    style: str | None = None,
    color: str | None = None,
    material: str | None = None,
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    in_stock: bool | None = None,
    q: str | None = Query(default=None, max_length=80),
    sort: str = Query(default="relevance", pattern="^(relevance|price_asc|price_desc|rating)$"),
    page: int = Query(default=1, ge=1, le=50),
    page_size: int = Query(default=24, ge=1, le=100),
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
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return ProductListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: str) -> Product:
    return get_repository().require(product_id, as_request_error=False)
