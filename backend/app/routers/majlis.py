"""Majlis API: generate a complete perimeter-seating layout in one call.

Separate from the family guide flow (which is per-category, step-by-step). A majlis is a
batch layout - the engine fills every wall at once - so this returns the full set of placed
items plus the achieved seat capacity.
"""

from fastapi import APIRouter
from pydantic import Field

from app.models.geometry import PlacedItem, Room, StrictModel
from app.models.preferences import Preferences
from app.services.majlis.generate import generate_majlis

router = APIRouter(prefix="/majlis", tags=["majlis"])


class MajlisGenerateRequest(StrictModel):
    room: Room
    preferences: Preferences = Field(default_factory=Preferences)


class MajlisGenerateResponse(StrictModel):
    placed_items: list[PlacedItem]
    seats: int
    note: str


@router.post("/generate", response_model=MajlisGenerateResponse)
def generate(req: MajlisGenerateRequest) -> MajlisGenerateResponse:
    result = generate_majlis(req.room, req.preferences)
    return MajlisGenerateResponse(placed_items=result.placed_items, seats=result.seats, note=result.note)
