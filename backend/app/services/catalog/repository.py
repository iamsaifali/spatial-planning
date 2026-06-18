"""In-memory product catalog loaded from the committed JSON seed."""

import json
from collections import defaultdict
from pathlib import Path

from app.errors import PRODUCT_NOT_FOUND, UNKNOWN_PRODUCT, AppError
from app.models.preferences import Preferences
from app.models.products import Product

SORTS = {
    "relevance": lambda p: (-p.rating, p.price),
    "price_asc": lambda p: (p.price, p.id),
    "price_desc": lambda p: (-p.price, p.id),
    "rating": lambda p: (-p.rating, p.price),
}


class CatalogRepository:
    def __init__(self, products: list[Product]):
        self._products: dict[str, Product] = {p.id: p for p in products}
        self._by_category: dict[str, list[Product]] = defaultdict(list)
        for p in products:
            self._by_category[p.category].append(p)

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
            product = Product(**entry)
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

    def category_stats(self) -> dict[str, dict[str, float]]:
        return self._stats

    def terciles(self, category: str) -> tuple[int, int]:
        return self._terciles.get(category, (0, 0))

    @staticmethod
    def _match_flags(product: Product, prefs: Preferences) -> tuple[bool, bool]:
        """(style_match, colour_match) against the user's preferences."""
        style_match = bool(prefs.styles) and any(s in prefs.styles for s in product.style_tags)
        wanted_colors = {c.lower() for c in prefs.colors}
        colour_match = bool(wanted_colors) and any(c.lower() in wanted_colors for c in product.colors)
        return style_match, colour_match

    def pool_for(self, category: str, prefs: Preferences) -> list[Product]:
        """Best-match-first candidate pool for a category - NEVER culled to empty.

        Style + colour are ranking signals, not hard gates: products matching both
        sort first, then one, then the rest. select_slots/scoring still re-rank by
        spatial fit + budget, but this guarantees a non-empty, preference-leaning pool.
        """
        items = self._by_category.get(category, [])

        def sort_key(p: Product):
            style_match, colour_match = self._match_flags(p, prefs)
            match_rank = 2 * int(style_match) + int(colour_match)  # 0..3
            return (not p.in_stock, -match_rank, -p.rating, p.price, p.id)

        return sorted(items, key=sort_key)

    def category_summary(self, prefs: Preferences) -> dict[str, dict]:
        """Per-category facts for the LLM Director - counts/price-bands/match-flags.

        This is the ONLY catalog information the LLM ever sees; never the products.
        """
        out: dict[str, dict] = {}
        for cat, items in self._by_category.items():
            if cat == "custom" or not items:
                continue
            prices = [p.price for p in items]
            flags = [self._match_flags(p, prefs) for p in items]
            out[cat] = {
                "count": len(items),
                "price_min": min(prices),
                "price_max": max(prices),
                "has_style_match": any(sm for sm, _ in flags),
                "has_colour_match": any(cm for _, cm in flags),
            }
        return out

    def search(
        self,
        category: str | None = None,
        style: str | None = None,
        color: str | None = None,
        material: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        in_stock: bool | None = None,
        q: str | None = None,
        sort: str = "relevance",
        page: int = 1,
        page_size: int = 24,
    ) -> tuple[list[Product], int]:
        items = self._by_category.get(category, []) if category else self.all()
        if style:
            items = [p for p in items if style in p.style_tags]
        if color:
            needle = color.lower()
            items = [p for p in items if any(needle in c.lower() for c in p.colors)]
        if material:
            needle = material.lower()
            items = [p for p in items if any(needle in m.lower() for m in p.materials)]
        if min_price is not None:
            items = [p for p in items if p.price >= min_price]
        if max_price is not None:
            items = [p for p in items if p.price <= max_price]
        if in_stock is not None:
            items = [p for p in items if p.in_stock == in_stock]
        if q:
            needle = q.lower()
            items = [
                p for p in items
                if needle in p.name.lower() or needle in p.brand.lower() or needle in p.category
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
