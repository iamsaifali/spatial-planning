# ZORY — Guided Shopping & Spatial Planning Platform

Draw your living-room floor plan and let ZORY guide you, one decision at a time, from an empty
canvas to a practical, beautiful, **shoppable** room layout.

| | |
|---|---|
| Backend | FastAPI (Python 3.12) · Shapely spatial engine · SQLite · OpenAI GPT-5.5 + gpt-image-2 |
| Frontend | Next.js 16 · React 19 · Tailwind CSS v4 · react-konva canvas · Zustand |

## What it does

1. **Draw the room** — walls (click-to-draw with snapping), doors with swing arcs, windows; or start
   from templates. Real-world cm scale with live dimension labels.
2. **ZORY reads the room** — a deterministic geometry engine (no LLM in the loop) finds usable walls,
   keep-clear zones, door swings, circulation corridors, the focal wall, and per-category placement zones.
3. **Guided furnishing** — Sofa → TV unit → Rug → Coffee table → Side tables → Accent chair →
   Lighting → Storage → Decor. Each step: a why-explained guidance message, a highlighted zone on the
   canvas, and 3 recommendations (Best match / Budget / Premium) scored on spatial fit, style, colour,
   budget, compatibility and availability.
4. **Soft placement guidance** — drag anything anywhere; ZORY warns when something blocks a walkway,
   door swing, or window and offers **Auto-fix**, **Show better spot**, or **Keep anyway**.
5. **See it** — **interactive 3D view** (Three.js: walls extruded from your plan with real door/window
   openings, parameterized 3D furniture, orbit/zoom/pan, dollhouse walls that hide toward the camera)
   plus an **AI photo preview** of the furnished room (gpt-image-2).
6. **Shop it** — room summary with completeness, missing essentials, upgrade ideas; add-all-to-cart;
   mock checkout; save & share designs via link. Prices display in **SAR or USD** (toggle in the top
   bar) — amounts are stored in the backend's base currency and converted with rates from `.env`.

GPT-5.5 only **phrases** deterministic spatial facts into friendly copy. With no API key the app is
fully functional: template copy + an honest offline assistant; only the AI photo preview is disabled.

## Run it

### Backend (port 8000)

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt   # first time only
cp .env.example .env                            # add OPENAI_API_KEY to enable AI copy + preview
.venv/bin/python scripts/download_images.py     # first time only: product photos + SVG fallbacks
.venv/bin/uvicorn app.main:app --port 8000
```

### Frontend (port 3000)

```bash
cd frontend
npm install        # first time only
npm run dev
```

Open http://localhost:3000 — the planner loads a sample room so you're never staring at a blank canvas.

### Tests

```bash
cd backend && .venv/bin/python -m pytest        # 41 geometry/recommendation/API tests
cd frontend && npm run lint && npm run build
```

## Repo layout

```
backend/    FastAPI app — see backend/README.md for API + engine details
frontend/   Next.js app — see frontend/README.md for component map
client_requirements/  original concept note
```

## Canvas shortcuts

`V` select · `W` draw walls · `D` door · `N` window · `M` measure · `R` rotate selection ·
arrows nudge (Shift = 1 cm) · `Del` delete · `F` fit · `+`/`−` zoom · `Cmd/Ctrl+Z` undo ·
`Cmd/Ctrl+Shift+Z` redo · `Esc` cancel/deselect · wheel zoom · drag empty canvas to pan ·
pinch + two-finger pan on touch devices.
