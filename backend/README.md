# ZORY backend

FastAPI + Shapely spatial-intelligence engine. All endpoints under `/api/v1`, stateless
(the room travels with each request; analyses are LRU-cached by a canonical room hash).

```bash
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                          # OPENAI_API_KEY optional but recommended
.venv/bin/python scripts/download_images.py   # seed product photos (SVG fallbacks always exist)
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/python -m pytest                    # test suite
```

## Architecture

```
app/
├── models/      pydantic v2 schemas (geometry in cm, x→right, y→down)
├── routers/     health rooms guide placement products summary render assistant designs checkout
└── services/
    ├── spatial/    deterministic geometry: walls/normals → keep-out (door swings, entry
    │               clearances, window strips) → circulation corridors → per-category
    │               placement zones → validation findings → minimal-displacement auto-fix
    ├── recommend/  scoring (35 spatial / 20 style / 10 colour / 15 budget / 15 compat / 5 avail),
    │               Best-Budget-Premium slotting with a relaxation ladder (never a silent bad fit)
    ├── guide/      the 9-step living-room flow + completeness weights
    ├── ai/         GPT-5.5 phrasing layer (strict JSON-schema outputs, 8s timeout,
    │               template fallback = identical facts, never 5xx) + gpt-image-2 render
    ├── catalog/    in-memory repository from app/data/catalog.json (100 products; prices
    │               in BASE_CURRENCY=USD, displayed as SAR/USD via CURRENCY_RATES in .env)
    └── persistence/ sqlite (saved designs + mock orders only)
```

Key conventions (pinned by tests in `tests/test_geometry_conventions.py`):

- Item rotation 0° = width along +x, front facing +y (screen-down). Positive rotation appears
  clockwise on screen.
- Wall inward normals are found empirically (point-containment probes), never by winding math.
- Every guidance/explanation string is generated from machine-checked facts (`reason_codes`,
  `fit_facts`) — the LLM may rephrase them but cannot invent dimensions or prices.

Error envelope everywhere: `{"error": {"code", "message", "details?"}}` with stable codes
(`ROOM_INVALID`, `OPENING_INVALID`, `NO_FIT`, `RENDER_DISABLED`, …).

## Regenerating the catalog

```bash
.venv/bin/python scripts/generate_catalog.py   # rewrites app/data/catalog.json deterministically
.venv/bin/python scripts/download_images.py    # refresh photos; --force to re-download
```
