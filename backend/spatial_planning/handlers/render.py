
from spatial_planning.config import get_settings
from spatial_planning.models.api import RenderRequest, RenderResponse
from spatial_planning.handlers._common import resolve_placed
from spatial_planning.services.ai.render_service import render as render_image
from spatial_planning.services.spatial.analyze import analyze_room



async def render(req: RenderRequest) -> RenderResponse:
    placed = resolve_placed(req.placed_items)
    analyze_room(req.room)  # room must be valid before we spend an image call
    settings = get_settings()
    image_b64, facts = await render_image(
        req.room, placed, req.preferences, req.canvas_png_b64, req.size, settings.resolve(settings.static_dir)
    )
    return RenderResponse(image_b64=image_b64, prompt_facts=facts)
