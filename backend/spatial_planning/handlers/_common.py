"""Shared request helpers for routers."""

from spatial_planning.config import get_settings
from spatial_planning.errors import DUPLICATE_INSTANCE, UNSUPPORTED_CURRENCY, AppError
from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.products import Product
from spatial_planning.services.catalog import get_repository
from spatial_planning.services.spatial.core import RoomAnalysis, WallData, ZoneData

PlacedProduct = tuple[PlacedItem, Product]


def _pseudo_product(item: PlacedItem) -> Product:
    """A user's own kept item: occupies space, costs nothing, never recommended."""
    spec = item.custom
    assert spec is not None
    return Product(
        id=item.product_id,
        name=spec.name,
        brand="Your item",
        category="custom",
        price=0,
        width_cm=spec.width_cm,
        depth_cm=spec.depth_cm,
        height_cm=spec.height_cm,
        style_tags=[],
        colors=[],
        materials=[],
        in_stock=True,
        delivery_days=1,
        rating=0,
        image_url="",
        is_walkable=False,
    )


def resolve_currency(requested: str | None) -> str:
    """Display currency for the request - validated against SUPPORTED_CURRENCIES."""
    settings = get_settings()
    if requested is None:
        return settings.default_currency
    code = requested.upper()
    if code not in settings.supported_currencies:
        raise AppError(
            code=UNSUPPORTED_CURRENCY,
            message=f"Currency '{requested}' is not supported. Use one of: "
            + ", ".join(settings.supported_currencies),
            status_code=422,
        )
    return code


def to_display_amount(base_amount: int | float, currency: str) -> int:
    """Convert a BASE_CURRENCY amount for display/order records (whole units)."""
    return round(base_amount * get_settings().rate_for(currency))


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


def zone_guidance_facts(
    category: str,
    analysis: RoomAnalysis,
    zones: list[ZoneData],
    placed: list[PlacedProduct],
) -> dict:
    facts: dict = {
        "category": category,
        "room_area_m2": round(analysis.area_cm2 / 10_000.0, 1),
        "placed_count": len(placed),
        "placed_categories": sorted({p.category for _i, p in placed}),
        "has_zone": bool(zones),
        "reason_codes": [],
    }
    if zones:
        best = zones[0]
        facts["reason_codes"] = best.reason_codes
        facts["zone_anchor"] = best.anchor_label
        if best.kind == "wall_band" and best.wall_index is not None:
            facts["wall_label"] = wall_label(analysis.walls[best.wall_index])
            if best.seg:
                facts["zone_len_cm"] = round(best.seg[1] - best.seg[0])
        elif best.lat_len:
            facts["zone_len_cm"] = round(best.lat_len)
    return facts
