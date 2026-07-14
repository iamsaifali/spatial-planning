"use client";

import { WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CanvasRoot } from "@/components/canvas/CanvasRoot";
import { CanvasToolbar } from "@/components/canvas/CanvasToolbar";
import { ItemActionsBar } from "@/components/canvas/ItemActionsBar";
import { OpeningEditor } from "@/components/canvas/OpeningEditor";
import { ZoomControls } from "@/components/canvas/ZoomControls";
import { Button } from "@/components/ui/Button";
import { Toasts } from "@/components/ui/Toasts";
import { ResumeDraftDialog, type PendingDraft } from "@/components/overlays/ResumeDraftDialog";
import { WarningPopover } from "@/components/overlays/WarningPopover";
import { View3DDialog } from "@/components/view3d/View3DDialog";
import { api, debounced } from "@/lib/api";
import { sampleRoom } from "@/lib/constants";
import { useCurrencyStore } from "@/stores/currencyStore";
import { useSceneStore } from "@/stores/sceneStore";
import type { PlacedItem, Room } from "@/types/api";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { BottomBar } from "./BottomBar";
import { TopBar } from "./TopBar";

const DRAFT_KEY = "zory-draft-v1";

export function PlannerShell({ skipDraftRestore = false }: { skipDraftRestore?: boolean }) {
  const [backendDown, setBackendDown] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<PendingDraft | null>(null);
  const bootstrapped = useRef(false);

  // bootstrap: rehydrate persisted stores, health, config, draft choice
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;

    // persisted stores use skipHydration so SSR matches the first client
    // paint; bring the saved values in now that we're safely mounted
    void usePrefsStore.persist.rehydrate();
    void useCurrencyStore.persist.rehydrate();

    api
      .health()
      .then(() => setBackendDown(false))
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
            const found = { room: draft.room, items: draft.items, savedAt: draft.savedAt };
            setTimeout(() => setPendingDraft(found), 0);
          }
        }
      } catch {
        localStorage.removeItem(DRAFT_KEY);
      }
    }
  }, [skipDraftRestore]);

  const continueDraft = () => {
    if (!pendingDraft) return;
    usePlannerStore
      .getState()
      .loadDesign(null, "My Living Room", pendingDraft.room, pendingDraft.items);
    setPendingDraft(null);
  };

  const startFresh = () => {
    localStorage.removeItem(DRAFT_KEY);
    usePlannerStore.getState().loadDesign(null, "My Living Room", sampleRoom(), []);
    setPendingDraft(null);
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
      .then(() => setBackendDown(false))
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
                python manage.py runserver 8000
              </code>{" "}
              in the <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">backend</code> folder, then retry.
            </p>
            <Button onClick={retryBackend}>Retry connection</Button>
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1">
          <main className="relative min-h-0 bg-bg" aria-label="Room canvas">
            <CanvasRoot />

            {/* floating chrome — sits BELOW the room-type / Assist bar (which is at top-3 z-20)
                so a selection bar never overlaps it */}
            <div className="pointer-events-none absolute inset-x-0 top-16 z-10 flex flex-col items-center gap-2 px-3">
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
          </main>
        </div>
      )}

      <BottomBar />

      <View3DDialog />
      <ResumeDraftDialog draft={pendingDraft} onContinue={continueDraft} onStartFresh={startFresh} />
      <Toasts />
    </div>
  );
}
