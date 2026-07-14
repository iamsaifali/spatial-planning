"""Internal (shapely-carrying) analysis structures shared across spatial services."""

from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.prepared import PreparedGeometry

from spatial_planning.models.analysis import Zone
from spatial_planning.models.geometry import Room
from spatial_planning.services.spatial.geometry_utils import Vec, poly_pts


@dataclass
class OpeningData:
    kind: str  # "door" | "window"
    id: str
    a: float  # start offset along wall
    b: float  # end offset along wall


@dataclass
class WallData:
    index: int
    start: Vec
    end: Vec
    length: float
    dir: Vec  # unit, start -> end
    normal: Vec  # unit, inward
    openings: list[OpeningData] = field(default_factory=list)
    clear_floor: list[tuple[float, float]] = field(default_factory=list)
    clear_solid: list[tuple[float, float]] = field(default_factory=list)
    is_longest_clear: bool = False
    is_focal: bool = False

    def point_at(self, t: float) -> Vec:
        return (self.start[0] + self.dir[0] * t, self.start[1] + self.dir[1] * t)


@dataclass
class EntryData:
    door_id: str
    point: Vec
    is_primary: bool = False


@dataclass
class CorridorData:
    id: str
    from_label: str
    to_label: str
    a: Vec
    b: Vec
    path: LineString
    polygon: Polygon


@dataclass
class ZoneData:
    id: str
    category: str
    polygon: Polygon
    score: float
    rotation_deg: float
    anchor_label: str
    reason_codes: list[str] = field(default_factory=list)
    kind: str = "free"  # wall_band | frame | free
    wall_index: int | None = None
    seg: tuple[float, float] | None = None
    band_depth: float = 0.0
    float_cm: float = 0.0  # wall_band: extra inward offset from the wall (floats the piece into the room)
    anchor_t: float | None = None  # wall_band: target position along the wall (else segment centre)
    origin: Vec | None = None  # frame zones: center of near edge
    fwd: Vec | None = None  # frame zones: unit forward
    lat: Vec | None = None  # frame zones: unit lateral
    fwd_len: float = 0.0
    lat_len: float = 0.0
    rank: int = 0

    def to_model(self) -> Zone:
        return Zone(
            id=self.id,
            category=self.category,  # type: ignore[arg-type]
            polygon=poly_pts(self.polygon),
            score=round(self.score, 3),
            suggested_rotation_deg=round(self.rotation_deg, 1),
            anchor=self.anchor_label,
            reason_codes=self.reason_codes,
            rank=self.rank,
        )


@dataclass
class RoomAnalysis:
    room: Room
    polygon: Polygon
    prepared: PreparedGeometry
    walls: list[WallData]
    entries: list[EntryData]
    swing_arcs: dict[str, Polygon]  # door_id -> arc
    entry_clearances: dict[str, Polygon]
    window_strips: dict[str, tuple[Polygon, float]]  # window_id -> (strip, sill height)
    keep_clear_union: BaseGeometry
    corridors: list[CorridorData]
    usable_area: BaseGeometry
    interior_anchor: Vec
    focal_wall_index: int | None
    longest_clear_wall_index: int | None
    analysis_hash: str
    notices: list[str] = field(default_factory=list)

    @property
    def area_cm2(self) -> float:
        return self.polygon.area

    @property
    def usable_cm2(self) -> float:
        return self.usable_area.area if not self.usable_area.is_empty else 0.0

    @property
    def diag_cm(self) -> float:
        minx, miny, maxx, maxy = self.polygon.bounds
        return ((maxx - minx) ** 2 + (maxy - miny) ** 2) ** 0.5
