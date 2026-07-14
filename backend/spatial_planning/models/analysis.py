from pydantic import Field

from spatial_planning.models.geometry import Point, StrictModel
from spatial_planning.models.products import Category


class Zone(StrictModel):
    id: str
    category: Category
    polygon: list[Point]
    score: float
    suggested_rotation_deg: float = 0
    anchor: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    rank: int = 0


class RoomIssue(StrictModel):
    code: str
    message: str
    wall_index: int | None = None
