# ZORY frontend

Next.js 16 (App Router, Turbopack) · React 19 · Tailwind CSS v4 (CSS-first `@theme` tokens in
`src/app/globals.css`) · react-konva canvas · Zustand (+ zundo undo/redo, persist for cart/prefs).

```bash
npm install
npm run dev      # http://localhost:3000 (backend expected on :8000)
npm run lint
npm run build
```

Set `NEXT_PUBLIC_API_BASE` to point at a non-default backend.

## Map

```
src/
├── app/                 /  /planner  /planner/[id]  + error/not-found pages
├── components/
│   ├── canvas/          Konva stage: RoomShape (walls, draggable corners, door/window glyphs),
│   │                    PlacedItemNode (top-view furniture, drag + rotate + live collision tint),
│   │                    Overlays (zones, corridors, ghosts), toolbar, templates, zoom
│   ├── guide/           step list, guidance card, Ask ZORY, preferences quiz
│   ├── products/        Recommended (Best/Budget/Premium cards) + All-products tabs
│   ├── overlays/        warning popover (Auto-fix / Show better / Keep anyway), room summary,
│   │                    cart, AI render dialog, save-share, mock checkout
│   ├── view3d/          Three.js room view (lazy-loaded): walls with door/window openings from
│   │                    the same room data, parameterized furniture, orbit controls, dollhouse
│   │                    wall hiding; wall thickness comes from /config (.env)
│   ├── layout/          PlannerShell (responsive shell), top/bottom bars, mobile step bar
│   └── ui/              Button, Chip, Dialog, Sheet, Toasts, skeletons, image fallback
├── stores/              plannerStore (room+items, undoable) · guideStore (steps, cached per
│                        room version) · cartStore · prefsStore · uiStore · productStore
└── lib/                 typed API client (error envelope, latest-wins aborts, debounce),
                         placement controller (add → validate → warn → fix loop),
                         client-side advisory geometry, SAR/USD money formatting, canvas snapshot
```

## Responsive behaviour

- ≥1280px: guide panel | canvas | products (3-pane; wider columns from 1920px via `3xl` token)
- 1024–1279px: step icon-rail | canvas | products
- 768–1023px: full-bleed canvas + right "Products" edge tab + slide-over panels
- <768px: full-bleed canvas, bottom step pill opens a Guide/Products bottom sheet; works to 320px
- Touch: one-finger drag items, drag-empty-space pan, pinch zoom; pointer hit targets ≥ 44px

Design rules enforced: solid colours only, **no gradients, no blue, no purple**; lucide-react SVG
icons (zero emojis); warm neutral palette tokens in `globals.css`. Prices display in **SAR or USD**
(TopBar toggle, SAR default) - amounts are stored in the backend's base currency and converted with
rates served by `/api/v1/config` (backed by `backend/.env`).
