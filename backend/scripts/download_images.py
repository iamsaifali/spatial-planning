"""Fetch product photos to static/products/ and pre-generate SVG fallbacks.

Every product ALWAYS gets an SVG placeholder; JPGs are layered on top when the
download succeeds, so the API never serves a dead image URL. Idempotent; pass
--force to re-download existing JPGs.

Run from the backend directory:
    .venv/bin/python scripts/download_images.py
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent.parent
CATALOG = BASE / "app" / "data" / "catalog.json"
OUT_DIR = BASE / "static" / "products"

CONCURRENCY = 8
TIMEOUT = 12.0

# Warm solid tints per category (no blue/purple anywhere).
TINTS = {
    "sofa": ("#EAE2D4", "#8A7B63"),
    "tv_unit": ("#E7DFD3", "#6B5D4A"),
    "rug": ("#F1E8DA", "#A98F68"),
    "coffee_table": ("#EFE7DB", "#7C6A52"),
    "side_table": ("#F3EDE3", "#8A7B63"),
    "accent_chair": ("#EDE4D5", "#946F4B"),
    "lighting": ("#F6EFE2", "#B08D4F"),
    "storage": ("#E9E1D2", "#6E5F49"),
    "decor": ("#ECEFE4", "#5F7350"),
}

GLYPHS = {
    "sofa": "M120 300 h560 a30 30 0 0 1 30 30 v90 h-620 v-90 a30 30 0 0 1 30-30 Z M90 330 a36 36 0 0 0 -36 36 v110 a24 24 0 0 0 24 24 h644 a24 24 0 0 0 24-24 v-110 a36 36 0 0 0 -72 0 v38 h-548 v-38 a36 36 0 0 0 -36-36 Z",
    "tv_unit": "M140 330 h520 v120 h-520 Z M160 350 h150 v80 h-150 Z M330 350 h140 v80 h-140 Z M490 350 h150 v80 h-150 Z M170 450 h30 v20 h-30 Z M600 450 h30 v20 h-30 Z",
    "rug": "M170 250 h460 v220 h-460 Z M200 280 h400 v160 h-400 Z M230 310 h340 v100 h-340 Z",
    "coffee_table": "M200 330 h400 v40 h-400 Z M230 370 h28 v90 h-28 Z M542 370 h28 v90 h-28 Z M310 410 h180 v16 h-180 Z",
    "side_table": "M310 300 h180 v34 h-180 Z M330 334 h22 v120 h-22 Z M448 334 h22 v120 h-22 Z",
    "accent_chair": "M300 270 a32 32 0 0 1 32-32 h136 a32 32 0 0 1 32 32 v110 h-200 Z M280 380 h240 v50 a20 20 0 0 1 -20 20 h-200 a20 20 0 0 1 -20-20 Z M300 450 h22 v40 h-22 Z M478 450 h22 v40 h-22 Z",
    "lighting": "M352 220 l96 0 l40 110 h-176 Z M392 330 h16 v160 h-16 Z M330 490 h140 v18 h-140 Z",
    "storage": "M240 220 h320 v260 h-320 Z M260 240 h135 v100 h-135 Z M405 240 h135 v100 h-135 Z M260 360 h135 v100 h-135 Z M405 360 h135 v100 h-135 Z",
    "decor": "M370 320 a30 60 0 0 1 60 0 l-8 90 h-44 Z M340 410 h120 l-14 70 h-92 Z M398 250 q40 -50 80 -20 q-44 6 -62 44 Z M402 250 q-40 -64 -86 -30 q48 2 70 48 Z",
}


def svg_placeholder(product: dict) -> str:
    bg, fg = TINTS.get(product["category"], ("#EFE9DD", "#7A6C55"))
    glyph = GLYPHS.get(product["category"], GLYPHS["decor"])
    name = product["name"].replace("&", "&amp;")
    dims = f'{product["width_cm"]:.0f} x {product["depth_cm"]:.0f} x {product["height_cm"]:.0f} cm'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">
<rect width="800" height="600" fill="{bg}"/>
<path d="{glyph}" fill="{fg}" opacity="0.85"/>
<text x="400" y="540" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="30" fill="#44403C">{name}</text>
<text x="400" y="575" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="22" fill="#78716C">{dims}</text>
</svg>
"""


async def fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, product: dict, force: bool) -> str:
    url = product.get("source_image_url")
    jpg = OUT_DIR / f"{product['id']}.jpg"
    if not url:
        return "no-url"
    if jpg.exists() and not force:
        return "cached"
    async with sem:
        try:
            r = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                jpg.write_bytes(r.content)
                return "ok"
            return f"http-{r.status_code}"
        except Exception as exc:  # noqa: BLE001 - fallback SVG covers any failure
            return f"error-{type(exc).__name__}"


async def main() -> None:
    force = "--force" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    products = json.loads(CATALOG.read_text())

    for product in products:
        svg = OUT_DIR / f"{product['id']}.svg"
        svg.write_text(svg_placeholder(product))

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers={"User-Agent": "zory-seed/1.0"}) as client:
        results = await asyncio.gather(*(fetch(client, sem, p, force) for p in products))

    ok = sum(1 for r in results if r in ("ok", "cached"))
    print(f"SVG fallbacks: {len(products)} | photos available: {ok}/{len(products)}")
    failures = [(p["id"], r) for p, r in zip(products, results) if r not in ("ok", "cached")]
    for pid, reason in failures:
        print(f"  fallback -> {pid}: {reason}")


if __name__ == "__main__":
    asyncio.run(main())
