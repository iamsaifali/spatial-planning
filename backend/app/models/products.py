from typing import Literal

from pydantic import Field

from app.models.geometry import StrictModel

Category = Literal[
    "sofa",
    "tv_unit",
    "rug",
    "coffee_table",
    "side_table",
    "accent_chair",
    "lighting",
    "storage",
    "decor",
    "custom",  # user's own kept items - never recommended, price 0
]

StyleTag = Literal["modern", "scandinavian", "industrial", "boho", "classic", "minimal"]

CATEGORY_LABELS: dict[str, str] = {
    "sofa": "Sofa",
    "tv_unit": "TV Unit",
    "rug": "Rug",
    "coffee_table": "Coffee Table",
    "side_table": "Side Table",
    "accent_chair": "Accent Chair",
    "lighting": "Lighting",
    "storage": "Storage",
    "decor": "Decor",
    "custom": "Your Item",
}


class Product(StrictModel):
    id: str
    name: str
    brand: str
    category: Category
    price: int = Field(ge=0)
    mrp: int | None = Field(default=None, ge=0)  # list price when discounted
    width_cm: float = Field(gt=0, le=1000)
    depth_cm: float = Field(gt=0, le=1000)
    height_cm: float = Field(gt=0, le=400)
    style_tags: list[StyleTag]
    colors: list[str]
    materials: list[str]
    in_stock: bool = True
    delivery_days: int = Field(ge=1, le=60)
    rating: float = Field(ge=0, le=5)
    attrs: dict[str, float] = Field(default_factory=dict)
    image_url: str = ""
    is_walkable: bool = False
    shape: Literal["rect", "round"] = "rect"
    description: str = ""
