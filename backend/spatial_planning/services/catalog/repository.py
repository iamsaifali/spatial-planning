"""In-memory product catalog loaded from the committed JSON seed."""

import json
from collections import defaultdict
from pathlib import Path

from spatial_planning.errors import PRODUCT_NOT_FOUND, UNKNOWN_PRODUCT, AppError
from spatial_planning.models.products import Product, placement_group
from spatial_planning.services.catalog.backfill import backfill_product

SORTS = {
    "relevance": lambda p: (p.price, p.id),
    "price_asc": lambda p: (p.price, p.id),
    "price_desc": lambda p: (-p.price, p.id),
}


class CatalogRepository:
    def __init__(self, products: list[Product]):
        self._products: dict[str, Product] = {p.id: p for p in products}
        # Group by PLACEMENT ROLE, not the raw store category, so the engine (which asks for
        # "sofa", "tv_unit", ... via in_category / stats) finds store items like "3-seater-sofa"
        # or "tv-table". Identity for the 10 roles, so the legacy catalog is unaffected.
        self._by_category: dict[str, list[Product]] = defaultdict(list)
        for p in products:
            self._by_category[placement_group(p.category)].append(p)

        self._stats: dict[str, dict[str, float]] = {}
        self._terciles: dict[str, tuple[int, int]] = {}
        for cat, items in self._by_category.items():
            widths = [p.width_cm for p in items]
            depths = [p.depth_cm for p in items]
            self._stats[cat] = {
                "min_w": min(widths),
                "max_w": max(widths),
                "min_d": min(depths),
                "max_d": max(depths),
            }
            prices = sorted(p.price for p in items)
            n = len(prices)
            self._terciles[cat] = (prices[max(0, n // 3 - 1)], prices[max(0, (2 * n) // 3 - 1)])

    @classmethod
    def load(cls, catalog_path: Path, static_dir: Path) -> "CatalogRepository":
        raw = json.loads(catalog_path.read_text())
        products: list[Product] = []
        product_dir = static_dir / "products"
        for entry in raw:
            entry.pop("source_image_url", None)
            # migrate legacy rows -> fill taxonomy defaults + infer seating_capacity
            product = Product(**backfill_product(entry))
            jpg = product_dir / f"{product.id}.jpg"
            svg = product_dir / f"{product.id}.svg"
            if jpg.exists():
                product.image_url = f"/static/products/{product.id}.jpg"
            elif svg.exists():
                product.image_url = f"/static/products/{product.id}.svg"
            else:
                product.image_url = f"/static/products/{product.id}.svg"
            products.append(product)
        return cls(products)

    def get(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def require(self, product_id: str, as_request_error: bool = True) -> Product:
        product = self._products.get(product_id)
        if product is None:
            raise AppError(
                code=UNKNOWN_PRODUCT if as_request_error else PRODUCT_NOT_FOUND,
                message=f"Unknown product '{product_id}'.",
                status_code=422 if as_request_error else 404,
            )
        return product

    def all(self) -> list[Product]:
        return list(self._products.values())

    def in_category(self, category: str) -> list[Product]:
        return list(self._by_category.get(category, []))

    def in_room_type(self, room_type: str) -> list[Product]:
        """Products suitable for a room type (e.g. "living_room", "majlis").

        Convenience for a future room-type-aware recommender pre-gate; the existing
        living-room flow doesn't call it, so behaviour is unchanged today.
        """
        return [p for p in self.all() if room_type in p.room_types]

    def category_stats(self) -> dict[str, dict[str, float]]:
        return self._stats

    def terciles(self, category: str) -> tuple[int, int]:
        return self._terciles.get(category, (0, 0))

    def search(
        self,
        category: str | None = None,
        style: str | None = None,
        color: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        q: str | None = None,
        room_type: str | None = None,
        sort: str = "relevance",
        page: int = 1,
        page_size: int = 24,
    ) -> tuple[list[Product], int]:
        items = self._by_category.get(category, []) if category else self.all()
        if style:
            items = [p for p in items if style in p.style_tags]
        if room_type:
            items = [p for p in items if room_type in p.room_types]
        if color:
            needle = color.lower()
            items = [p for p in items if any(needle in c.lower() for c in p.colors)]
        if min_price is not None:
            items = [p for p in items if p.price >= min_price]
        if max_price is not None:
            items = [p for p in items if p.price <= max_price]
        if q:
            needle = q.lower()
            items = [
                p for p in items
                if needle in p.name.lower() or needle in p.category
            ]
        items = sorted(items, key=SORTS.get(sort, SORTS["relevance"]))
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total


_repository: CatalogRepository | None = None


def set_repository(repo: CatalogRepository) -> None:
    global _repository
    _repository = repo


def get_repository() -> CatalogRepository:
    if _repository is None:
        raise RuntimeError("Catalog repository not initialised")
    return _repository
