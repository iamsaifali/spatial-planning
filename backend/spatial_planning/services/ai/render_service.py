"""AI photo preview via gpt-image-2: canvas snapshot + layout facts -> render."""

import base64
import binascii
import logging
from pathlib import Path

from spatial_planning.config import get_settings
from spatial_planning.errors import (
    PNG_TOO_LARGE,
    RENDER_DISABLED,
    RENDER_FAILED,
    RENDER_REJECTED,
    AppError,
)
from spatial_planning.models.geometry import PlacedItem, Room
from spatial_planning.models.preferences import Preferences
from spatial_planning.models.products import CATEGORY_LABELS, Product

logger = logging.getLogger("zory.render")


def _snap16(value: int) -> int:
    return max(256, min(2048, (value // 16) * 16))


def normalize_size(size: str | None) -> str:
    default = get_settings().render_default_size
    if not size:
        return default
    try:
        w_str, h_str = size.lower().split("x")
        w, h = _snap16(int(w_str)), _snap16(int(h_str))
        ratio = w / h
        if ratio > 3 or ratio < 1 / 3:
            return default
        return f"{w}x{h}"
    except (ValueError, ZeroDivisionError):
        return default


def _position_phrase(x: float, y: float, room: Room) -> str:
    xs = [v[0] for v in room.vertices]
    ys = [v[1] for v in room.vertices]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    fx = (x - minx) / max(maxx - minx, 1)
    fy = (y - miny) / max(maxy - miny, 1)
    col = "left" if fx < 0.34 else ("right" if fx > 0.66 else "center")
    row = "top" if fy < 0.34 else ("bottom" if fy > 0.66 else "middle")
    if col == "center" and row == "middle":
        return "in the middle of the room"
    if col == "center":
        return f"along the {row} wall"
    if row == "middle":
        return f"along the {col} wall"
    return f"in the {row}-{col} corner"


def build_prompt(
    room: Room,
    placed: list[tuple[PlacedItem, Product]],
    prefs: Preferences,
) -> tuple[str, dict]:
    xs = [v[0] for v in room.vertices]
    ys = [v[1] for v in room.vertices]
    w_m = (max(xs) - min(xs)) / 100.0
    d_m = (max(ys) - min(ys)) / 100.0

    item_lines = []
    for item, product in placed:
        colors = product.colors[0] if product.colors else "neutral"
        materials = product.materials[0] if product.materials else ""
        label = CATEGORY_LABELS.get(product.category, product.category).lower()
        item_lines.append(
            f"- {product.name} ({label}, {colors} {materials}, "
            f"{product.width_cm:.0f}x{product.depth_cm:.0f} cm) {_position_phrase(item.x, item.y, room)}"
        )

    style = ", ".join(prefs.styles) if prefs.styles else "warm contemporary"
    facts = {
        "room_w_m": round(w_m, 1),
        "room_d_m": round(d_m, 1),
        "wall_height_cm": room.wall_height_cm,
        "items": len(placed),
        "style": style,
        "windows": len(room.windows),
        "doors": len(room.doors),
    }
    prompt = (
        f"Photorealistic eye-level interior photograph of a {w_m:.1f} m x {d_m:.1f} m living room, "
        f"{room.wall_height_cm:.0f} cm ceilings, {style} style, warm neutral palette "
        "(off-white walls, light wood floor), soft natural daylight"
        + (f" from {len(room.windows)} window{'s' if len(room.windows) != 1 else ''}" if room.windows else "")
        + ". The FIRST reference image is the top-down floor plan of this exact room - follow its layout "
        "and furniture positions faithfully. Furniture in the room:\n"
        + "\n".join(item_lines)
        + "\nOther reference images show the actual products to depict. "
        "No people, no text, no watermarks. Realistic proportions and shadows."
    )
    return prompt, facts


async def render(
    room: Room,
    placed: list[tuple[PlacedItem, Product]],
    prefs: Preferences,
    canvas_png_b64: str,
    size: str | None,
    static_dir: Path,
) -> tuple[str, dict]:
    settings = get_settings()
    if not settings.llm_enabled:
        raise AppError(
            code=RENDER_DISABLED,
            message="AI preview needs an OpenAI API key. Add OPENAI_API_KEY to backend/.env to enable it.",
            status_code=503,
        )

    raw = canvas_png_b64.split(",", 1)[-1]  # tolerate data: URLs
    try:
        png_bytes = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as err:
        raise AppError(code=RENDER_FAILED, message="canvas_png_b64 is not valid base64.", status_code=422) from err
    if len(png_bytes) > settings.max_render_png_bytes:
        raise AppError(
            code=PNG_TOO_LARGE,
            message="Canvas snapshot exceeds 4 MB - zoom to fit before generating.",
            status_code=413,
        )

    prompt, facts = build_prompt(room, placed, prefs)
    out_size = normalize_size(size)
    facts["size"] = out_size

    images: list[tuple[str, bytes, str]] = [("canvas.png", png_bytes, "image/png")]
    seen_products = 0
    for _item, product in sorted(placed, key=lambda ip: -ip[1].width_cm):
        if seen_products >= settings.render_max_ref_images:
            break
        jpg = static_dir / "products" / f"{product.id}.jpg"
        if jpg.exists():
            images.append((f"{product.id}.jpg", jpg.read_bytes(), "image/jpeg"))
            seen_products += 1

    from openai import APIError, AsyncOpenAI, BadRequestError

    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.render_timeout_s, max_retries=0)
    try:
        result = await client.images.edit(
            model=settings.openai_image_model,
            image=images,
            prompt=prompt,
            size=out_size,
        )
    except BadRequestError as err:
        logger.warning("Render rejected: %s", err)
        raise AppError(
            code=RENDER_REJECTED,
            message="The image service rejected this render request. Try simplifying the room or removing custom labels.",
            status_code=422,
        ) from err
    except APIError as err:
        logger.error("Render failed: %s", err)
        raise AppError(
            code=RENDER_FAILED,
            message="The image service is unavailable right now. Please try again in a moment.",
            status_code=502,
        ) from err

    if not result.data or not result.data[0].b64_json:
        raise AppError(code=RENDER_FAILED, message="The image service returned no image.", status_code=502)
    return result.data[0].b64_json, facts
