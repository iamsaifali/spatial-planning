"""Room geometry schemas.

Conventions (pinned by tests):
- All lengths in cm. Canvas axes: x grows right, y grows DOWN (screen space).
- Walls are the edges of the vertex polygon: wall i = vertices[i] -> vertices[(i+1) % n].
- Door/window positions are 1-D offsets along their wall, measured from the
  wall's start vertex.
- Item rotation: at 0 deg, width lies along +x and the item's front faces +y.
"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Point = tuple[float, float]

MAX_COORD_CM = 10_000.0
MAX_BBOX_CM = 3_000.0
MIN_AREA_CM2 = 20_000.0  # 2 m^2


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Door(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    wall_index: int = Field(ge=0)
    offset_cm: float = Field(ge=0)
    width_cm: float = Field(ge=55, le=250)
    height_cm: float = Field(default=210, ge=180, le=300)  # drives the 3D lintel
    swing: Literal["inward", "outward", "sliding", "opening_only"] = "inward"
    hinge: Literal["left", "right"] = "left"


class Window(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    wall_index: int = Field(ge=0)
    offset_cm: float = Field(ge=0)
    width_cm: float = Field(ge=30, le=500)
    sill_height_cm: float = Field(default=90, ge=0, le=250)
    height_cm: float = Field(default=120, ge=20, le=400)


class Room(StrictModel):
    vertices: list[Point] = Field(min_length=3, max_length=40)
    doors: list[Door] = Field(default_factory=list, max_length=8)
    windows: list[Window] = Field(default_factory=list, max_length=12)
    wall_height_cm: float = Field(default=270, ge=200, le=600)

    @field_validator("vertices")
    @classmethod
    def _check_coords(cls, v: list[Point]) -> list[Point]:
        for x, y in v:
            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError("vertex coordinates must be finite numbers")
            if abs(x) > MAX_COORD_CM or abs(y) > MAX_COORD_CM:
                raise ValueError(f"vertex coordinates must be within +/-{MAX_COORD_CM} cm")
        return v

    @model_validator(mode="after")
    def _check_opening_ids(self) -> "Room":
        ids = [d.id for d in self.doors] + [w.id for w in self.windows]
        if len(ids) != len(set(ids)):
            raise ValueError("door/window ids must be unique")
        return self


class Pose(StrictModel):
    x: float
    y: float
    rotation_deg: float = 0

    @field_validator("x", "y")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("coordinates must be finite")
        return v

    @field_validator("rotation_deg")
    @classmethod
    def _norm_rotation(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("rotation must be finite")
        return round(v % 360.0, 2)


class CustomItemSpec(StrictModel):
    """Dimensions for an item the user already owns (doc 5: 'existing items you want to keep')."""

    name: str = Field(min_length=1, max_length=80)
    width_cm: float = Field(gt=0, le=1000)
    depth_cm: float = Field(gt=0, le=1000)
    height_cm: float = Field(default=75, gt=0, le=400)


class PlacedItem(Pose):
    instance_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=64)
    zone_id: str | None = None
    custom: CustomItemSpec | None = None
