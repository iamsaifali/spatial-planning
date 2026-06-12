from pydantic import Field

from app.models.geometry import Point, StrictModel
from app.models.products import Category


class OpeningSpan(StrictModel):
    kind: str  # "door" | "window"
    id: str
    start_cm: float
    end_cm: float


class WallInfo(StrictModel):
    index: int
    start: Point
    end: Point
    length_cm: float
    inward_normal: Point
    openings: list[OpeningSpan] = Field(default_factory=list)
    clear_floor_segments: list[tuple[float, float]] = Field(default_factory=list)
    clear_solid_segments: list[tuple[float, float]] = Field(default_factory=list)
    is_longest_clear: bool = False
    is_focal: bool = False


class Entry(StrictModel):
    door_id: str
    point: Point
    is_primary: bool = False


class Corridor(StrictModel):
    id: str
    from_label: str
    to_label: str
    polyline: list[Point]
    polygon: list[Point]
    width_cm: float = 80


class Zone(StrictModel):
    id: str
    category: Category
    polygon: list[Point]
    score: float
    suggested_rotation_deg: float = 0
    anchor: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    rank: int = 0


class RoomMetrics(StrictModel):
    area_m2: float
    perimeter_cm: float
    bbox_w_cm: float
    bbox_h_cm: float


class AnalysisResponse(StrictModel):
    analysis_hash: str
    metrics: RoomMetrics
    walls: list[WallInfo]
    entries: list[Entry]
    keep_clear: list[list[Point]]
    window_strips: list[list[Point]]
    corridors: list[Corridor]
    usable_area: list[list[Point]]
    focal_wall_index: int | None = None
    zones: list[Zone]
    notices: list[str] = Field(default_factory=list)


class RoomIssue(StrictModel):
    code: str
    message: str
    wall_index: int | None = None


class RoomValidateResponse(StrictModel):
    valid: bool
    issues: list[RoomIssue] = Field(default_factory=list)
