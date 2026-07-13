"""Shared type aliases for the recipe layer (kept local to avoid router imports)."""

from spatial_planning.models.geometry import PlacedItem
from spatial_planning.models.products import Product

PlacedProduct = tuple[PlacedItem, Product]
