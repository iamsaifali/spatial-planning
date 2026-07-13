from collections import Counter


from spatial_planning.errors import EMPTY_CART, AppError
from spatial_planning.models.api import CheckoutRequest, OrderLine, OrderResponse
from spatial_planning.handlers._common import resolve_currency, to_display_amount
from spatial_planning.services.catalog import get_repository
from spatial_planning.services.persistence import designs_repo, orders_repo



def checkout(req: CheckoutRequest) -> OrderResponse:
    repo = get_repository()

    qty_by_product: Counter[str] = Counter()
    if req.items:
        for line in req.items:
            qty_by_product[line.product_id] += line.qty
    elif req.design_id:
        design = designs_repo.get_design(req.design_id)
        for item in design.get("placed_items", []):
            qty_by_product[item["product_id"]] += 1

    if not qty_by_product:
        raise AppError(code=EMPTY_CART, message="There is nothing to check out.", status_code=422)

    out_of_stock: list[str] = []
    lines: list[OrderLine] = []
    eta = 1
    for product_id, qty in sorted(qty_by_product.items()):
        product = repo.require(product_id)
        if not product.in_stock:
            out_of_stock.append(product.name)
            continue
        lines.append(
            OrderLine(product_id=product.id, name=product.name, qty=qty, unit_price=product.price)
        )
        eta = max(eta, product.delivery_days)

    if out_of_stock:
        raise AppError(
            code="OUT_OF_STOCK",
            message="Some items are out of stock: " + ", ".join(out_of_stock),
            status_code=409,
            details={"out_of_stock": out_of_stock},
        )

    currency = resolve_currency(req.currency)
    total = sum(line.unit_price * line.qty for line in lines)
    order = orders_repo.create_order(
        [line.model_dump() for line in lines],
        req.contact.model_dump(),
        total,
        currency,
        to_display_amount(total, currency),
        eta,
        req.design_id,
    )
    return OrderResponse(**order)


def get_order(order_id: str) -> OrderResponse:
    return OrderResponse(**orders_repo.get_order(order_id))
