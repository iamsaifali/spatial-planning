"""Shared type aliases for the recipe layer (kept local to avoid router imports)."""

from app.models.geometry import PlacedItem
from app.models.products import Product

PlacedProduct = tuple[PlacedItem, Product]
