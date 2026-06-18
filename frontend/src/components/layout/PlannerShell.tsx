"use client";

import { ArrowRight, PackageOpen, WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CanvasRoot } from "@/components/canvas/CanvasRoot";
import { CanvasToolbar } from "@/components/canvas/CanvasToolbar";
import { ItemActionsBar } from "@/components/canvas/ItemActionsBar";
import { OpeningEditor } from "@/components/canvas/OpeningEditor";
import { ZoomControls } from "@/components/canvas/ZoomControls";
import { GuidePanel, GuidePanelContent, StepRail } from "@/components/guide/GuidePanel";
import { PreferencesDialog } from "@/components/guide/PreferencesDialog";
import { ProductPanel, ProductPanelContent } from "@/components/products/ProductPanel";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { Toasts } from "@/components/ui/Toasts";
import { CartDrawer } from "@/components/overlays/CartDrawer";
import { CheckoutDialog } from "@/components/overlays/CheckoutDialog";
import { RenderDialog } from "@/components/overlays/RenderDialog";
import { ResumeDraftDialog, type PendingDraft } from "@/components/overlays/ResumeDraftDialog";
import { RoomSetupDialog } from "@/components/overlays/RoomSetupDialog";
import { RoomSummarySheet } from "@/components/overlays/RoomSummarySheet";
import { SaveShareDialog } from "@/components/overlays/SaveShareDialog";
import { WarningPopover } from "@/components/overlays/WarningPopover";
import { View3DDialog } from "@/components/view3d/View3DDialog";
import { api, debounced } from "@/lib/api";
import { blankRoom, sampleRoom } from "@/lib/constants";
import { revalidateAll } from "@/lib/placement";
import { useCartStore } from "@/stores/cartStore";
import { useCurrencyStore } from "@/stores/currencyStore";
import { useFavoritesStore } from "@/stores/favoritesStore";
import { useGuideStore } from "@/stores/guideStore";
import { useSceneStore } from "@/stores/sceneStore";
import type { PlacedItem, Room } from "@/types/api";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import { BottomBar } from "./BottomBar";
import { MobileStepBar } from "./MobileStepBar";
import { TopBar } from "./TopBar";

const DRAFT_KEY = "zory-draft-v1";

export function PlannerShell({ skipDraftRestore = false }: { skipDraftRestore?: boolean }) {
  const [renderEnabled, setRenderEnabled] = useState(false);
  const [backendDown, setBackendDown] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<PendingDraft | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const bootstrapped = useRef(false);

  const roomVersion = usePlannerStore((s) => s.roomVersion);
  const planningStarted = useGuideStore((s) => s.planningStarted);
  const roomReady = usePlannerStore((s) => s.room.vertices.length >= 3);
  const guideSheetOpen = useUiStore((s) => s.guideSheetOpen);
  const productsSheetOpen = useUiStore((s) => s.productsSheetOpen);
  const leftPanelOpen = useUiStore((s) => s.leftPanelOpen);
  const setSheet = useUiStore((s) => s.setSheet);

  // bootstrap: rehydrate persisted stores, products, health, draft choice,
  // first analysis + step
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;

    // persisted stores use skipHydration so SSR matches the first client
    // paint; bring the saved values in now that we're safely mounted
    void useCartStore.persist.rehydrate();
    void usePrefsStore.persist.rehydrate();
    void useFavoritesStore.persist.rehydrate();
    void useCurrencyStore.persist.rehydrate();

    void useProductStore.getState().loadAll();

    api
      .health()
      .then((h) => {
        setRenderEnabled(h.render_enabled);
        setBackendDown(false);
      })
      .catch(() => setBackendDown(true));

    // currency + scene geometry come from the backend's .env via /config
    api
      .config()
      .then((cfg) => {
        useCurrencyStore.getState().applyConfig(cfg.currency);
        useSceneStore.getState().applyConfig(cfg.scene);
      })
      .catch(() => {
        // fallback defaults in the stores keep everything working
      });

    let hasDraft = false;
    if (!skipDraftRestore && !usePlannerStore.getState().designId) {
      try {
        const raw = localStorage.getItem(DRAFT_KEY);
        if (raw) {
          const draft = JSON.parse(raw) as {
            version: number;
            room: Room;
            items: PlacedItem[];
            savedAt?: number;
          };
          const pristine = JSON.stringify(draft.room) === JSON.stringify(sampleRoom());
          if (
            draft.version === 1 &&
            draft.room &&
            Array.isArray(draft.items) &&
            (draft.items.length > 0 || !pristine)
          ) {
            // a meaningful draft exists - let the user choose continue vs fresh
            // (deferred: avoids a synchronous setState inside the effect body)
            const found = { room: draft.room, items: draft.items, savedAt: draft.savedAt };
            hasDraft = true;
            setTimeout(() => setPendingDraft(found), 0);
          }
        }
      } catch {
        localStorage.removeItem(DRAFT_KEY);
      }
    }

    // Pipeline is gated: it only runs once the user commits to a room.
    if (usePlannerStore.getState().designId) {
      // a shared/saved design was loaded by /planner/[id] - plan it immediately
      useGuideStore.getState().startPlanning();
    } else if (!hasDraft) {
      // fresh session, nothing saved - ask how to begin (draw vs sample)
      setTimeout(() => setSetupOpen(true), 0);
    }
    // if a draft exists, ResumeDraftDialog decides (continue -> plan, fresh -> setup)
  }, [skipDraftRestore]);

  const continueDraft = () => {
    if (!pendingDraft) return;
    usePlannerStore
      .getState()
      .loadDesign(null, "My Living Room", pendingDraft.room, pendingDraft.items);
    setPendingDraft(null);
    useGuideStore.getState().startPlanning();
    useUiStore.getState().toast("info", "Restored your last draft.");
  };

  const startFresh = () => {
    localStorage.removeItem(DRAFT_KEY);
    usePlannerStore.getState().loadDesign(null, "My Living Room", blankRoom(), []);
    useGuideStore.getState().reset();
    useUiStore.getState().select(null);
    useUiStore.getState().requestFit();
    setPendingDraft(null);
    setSetupOpen(true);
  };

  // --- room setup choices ----------------------------------------------------
  const drawOwnRoom = () => {
    usePlannerStore.getState().loadDesign(null, "My Living Room", blankRoom(), []);
    useGuideStore.getState().reset();
    useUiStore.getState().select(null);
    useUiStore.getState().setTool("wall");
    useUiStore.getState().requestFit();
    setSetupOpen(false);
  };

  const useSampleRoom = () => {
    usePlannerStore.getState().loadDesign(null, "My Living Room", sampleRoom(), []);
    useGuideStore.getState().reset();
    useUiStore.getState().select(null);
    useUiStore.getState().requestFit();
    setSetupOpen(false);
    // ask preferences first - the plan is generated from the answers (or skip)
    useUiStore.getState().setSheet("prefsOpen", true);
  };

  // autosave draft (light throttle via debounce)
  useEffect(() => {
    const save = debounced(() => {
      const { room, items } = usePlannerStore.getState();
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ version: 1, room, items, savedAt: Date.now() }));
      } catch {
        // storage full/unavailable - skip silently
      }
    }, 800);
    const unsub = usePlannerStore.subscribe(() => save());
    return () => {
      unsub();
      save.cancel();
    };
  }, []);

  // room edits -> re-analyze, refresh step, revalidate placements
  const lastVersion = useRef(roomVersion);
  useEffect(() => {
    if (roomVersion === lastVersion.current) return;
    lastVersion.current = roomVersion;
    if (!useGuideStore.getState().planningStarted) return; // still drawing in setup
    const run = debounced(() => {
      const guide = useGuideStore.getState();
      void guide.fetchAnalysis();
      void guide.fetchStep(undefined, true);
      void revalidateAll();
    }, 600);
    run();
    return () => run.cancel();
  }, [roomVersion]);

  // warn before leaving with unsaved work
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (usePlannerStore.getState().dirtySinceSave && usePlannerStore.getState().items.length > 0) {
        e.preventDefault();
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);

  const retryBackend = () => {
    setBackendDown(false);
    api
      .health()
      .then((h) => {
        setRenderEnabled(h.render_enabled);
        if (useGuideStore.getState().planningStarted) {
          void useGuideStore.getState().fetchAnalysis();
          void useGuideStore.getState().fetchPlan();
          void useGuideStore.getState().fetchStep(undefined, true);
        }
        void useProductStore.getState().loadAll();
      })
      .catch(() => setBackendDown(true));
  };

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar />

      {backendDown ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="flex max-w-sm flex-col items-center gap-3 text-center">
            <WifiOff className="h-10 w-10 text-ink-faint" />
            <h2 className="text-lg font-bold">Can&apos;t reach the ZORY engine</h2>
            <p className="text-sm leading-6 text-ink-soft">
              Start the backend with{" "}
              <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">
                uvicorn app.main:app --port 8000
              </code>{" "}
              in the <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">backend</code> folder, then retry.
            </p>
            <Button onClick={retryBackend}>Retry connection</Button>
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[64px_1fr_340px] xl:grid-cols-[300px_1fr_360px] 3xl:grid-cols-[340px_1fr_420px]">
          <GuidePanel />
          <StepRail />

          <main className="relative min-h-0 bg-bg" aria-label="Room canvas">
            <CanvasRoot />

            {/* floating chrome */}
            <div className="pointer-events-none absolute inset-x-0 top-3 z-10 flex flex-col items-center gap-2 px-3">
              {!planningStarted && !setupOpen && (
                <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-line bg-surface px-3 py-1.5 shadow-soft">
                  <span className="text-xs font-medium text-ink-soft">
                    {roomReady ? "Your room is ready." : "Draw your walls, then start."}
                  </span>
                  <Button
                    size="sm"
                    disabled={!roomReady}
                    onClick={() => useUiStore.getState().setSheet("prefsOpen", true)}
                  >
                    Start planning
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                  <button
                    onClick={() => setSetupOpen(true)}
                    className="text-[11px] font-medium text-ink-faint hover:text-ink"
                  >
                    Start over
                  </button>
                </div>
              )}
              <OpeningEditor />
              <ItemActionsBar />
              <WarningPopover />
            </div>
            <div className="pointer-events-none absolute inset-x-0 bottom-3 z-10 flex justify-center px-3">
              <CanvasToolbar />
            </div>
            <div className="pointer-events-none absolute top-1/2 right-2 z-10 -translate-y-1/2 sm:top-auto sm:right-3 sm:bottom-3 sm:translate-y-0">
              <ZoomControls />
            </div>

            {/* md-only edge tab to open products */}
            <button
              onClick={() => setSheet("productsSheetOpen", true)}
              className="absolute top-1/2 right-0 z-10 hidden -translate-y-1/2 items-center gap-1.5 rounded-l-lg border border-r-0 border-line bg-surface px-2 py-3 text-xs font-semibold text-ink-soft shadow-soft hover:text-ink md:flex lg:hidden"
              aria-label="Open products panel"
            >
              <PackageOpen className="h-4 w-4" />
              <span className="[writing-mode:vertical-rl]">Products</span>
            </button>
          </main>

          <ProductPanel />
        </div>
      )}

      <BottomBar />
      <MobileStepBar />

      {/* phone: guide + recommendations bottom sheet */}
      <Sheet
        open={guideSheetOpen}
        onClose={() => setSheet("guideSheetOpen", false)}
        title="Room guide"
        side="bottom"
      >
        <MobileGuideTabs />
      </Sheet>

      {/* md: products slide-over */}
      <Sheet
        open={productsSheetOpen}
        onClose={() => setSheet("productsSheetOpen", false)}
        title="Products"
        side="right"
        widthClass="sm:max-w-sm"
      >
        <ProductPanelContent />
      </Sheet>

      {/* lg rail: full guide drawer */}
      <Sheet
        open={leftPanelOpen}
        onClose={() => setSheet("leftPanelOpen", false)}
        title="Room guide"
        side="left"
        widthClass="sm:max-w-sm"
      >
        <GuidePanelContent />
      </Sheet>

      <RoomSummarySheet />
      <CartDrawer />
      <CheckoutDialog />
      <SaveShareDialog />
      <RenderDialog renderEnabled={renderEnabled} />
      <View3DDialog />
      <PreferencesDialog />
      <ResumeDraftDialog draft={pendingDraft} onContinue={continueDraft} onStartFresh={startFresh} />
      <RoomSetupDialog open={setupOpen} onDrawOwn={drawOwnRoom} onUseSample={useSampleRoom} />
      <Toasts />
    </div>
  );
}

function MobileGuideTabs() {
  const [tab, setTab] = useState<"guide" | "shop">("guide");
  return (
    <div className="flex h-[70dvh] flex-col">
      <div className="flex gap-1 border-b border-line p-2">
        {(["guide", "shop"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            aria-pressed={tab === t}
            className={`flex-1 rounded-full px-3 py-1.5 text-xs font-semibold ${
              tab === t ? "bg-accent text-accent-ink" : "text-ink-soft"
            }`}
          >
            {t === "guide" ? "Guide" : "Products"}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">{tab === "guide" ? <GuidePanelContent /> : <ProductPanelContent />}</div>
    </div>
  );
}
