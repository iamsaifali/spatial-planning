from fastapi import APIRouter

from app.config import get_settings
from app.models.api import RenderRequest, RenderResponse
from app.routers._common import resolve_placed
from app.services.ai.render_service import render as render_image
from app.services.spatial.analyze import analyze_room

router = APIRouter(tags=["render"])


@router.post("/render", response_model=RenderResponse)
async def render(req: RenderRequest) -> RenderResponse:
    placed = resolve_placed(req.placed_items)
    analyze_room(req.room)  # room must be valid before we spend an image call
    settings = get_settings()
    image_b64, facts = await render_image(
        req.room, placed, req.preferences, req.canvas_png_b64, req.size, settings.resolve(settings.static_dir)
    )
    return RenderResponse(image_b64=image_b64, prompt_facts=facts)
