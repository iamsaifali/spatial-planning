"use client";

import { Camera, Download, ImageOff, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { api, ApiError } from "@/lib/api";
import { snapshotCanvas } from "@/lib/canvasExport";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useUiStore } from "@/stores/uiStore";

type Phase =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "done"; image: string }
  | { kind: "error"; message: string; code?: string };

export function RenderDialog({ renderEnabled }: { renderEnabled: boolean }) {
  const open = useUiStore((s) => s.renderOpen);
  const setSheet = useUiStore((s) => s.setSheet);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async () => {
    const { room, items } = usePlannerStore.getState();
    if (items.length === 0) {
      setPhase({ kind: "error", message: "Place a few products first - the preview renders your furnished room." });
      return;
    }
    const png = snapshotCanvas();
    if (!png) {
      setPhase({ kind: "error", message: "Couldn't capture the canvas. Try again." });
      return;
    }
    setPhase({ kind: "working" });
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const prefs = usePrefsStore.getState().preferences;
      const res = await api.render(room, items, prefs, png, controller.signal);
      setPhase({ kind: "done", image: `data:image/png;base64,${res.image_b64}` });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (err instanceof ApiError) {
        setPhase({ kind: "error", message: err.message, code: err.code });
      } else {
        setPhase({ kind: "error", message: "The preview failed. Please try again." });
      }
    }
  }, []);

  const [prevOpen, setPrevOpen] = useState(open);
  if (prevOpen !== open) {
    setPrevOpen(open);
    if (!open) setPhase({ kind: "idle" });
  }
  useEffect(() => {
    if (!open) abortRef.current?.abort();
  }, [open]);

  const close = () => setSheet("renderOpen", false);

  return (
    <Dialog open={open} onClose={close} title="AI photo preview" wide>
      <div className="space-y-4">
        {!renderEnabled ? (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface-2/60 p-8 text-center">
            <ImageOff className="h-8 w-8 text-ink-faint" />
            <p className="text-sm font-semibold">AI preview is not configured</p>
            <p className="max-w-sm text-xs leading-5 text-ink-soft">
              Add <code className="rounded bg-surface-2 px-1">OPENAI_API_KEY</code> to{" "}
              <code className="rounded bg-surface-2 px-1">backend/.env</code> and restart the backend to generate
              photorealistic previews of your room with gpt-image-2.
            </p>
          </div>
        ) : phase.kind === "idle" ? (
          <div className="flex flex-col items-center gap-4 rounded-lg bg-surface-2/60 p-8 text-center">
            <Camera className="h-8 w-8 text-amber-deep" />
            <p className="max-w-sm text-sm leading-6 text-ink-soft">
              ZORY sends your floor plan and product list to gpt-image-2 and returns a photorealistic
              eye-level photo of the furnished room.
            </p>
            <Button onClick={() => void start()}>
              <Camera className="h-4 w-4" />
              Generate preview
            </Button>
            <p className="text-[11px] text-ink-faint">Usually takes 30-60 seconds</p>
          </div>
        ) : phase.kind === "working" ? (
          <div className="flex flex-col items-center gap-4 p-10 text-center">
            <div className="relative h-14 w-14">
              <div className="absolute inset-0 animate-spin rounded-full border-[3px] border-beige-100 border-t-amber" />
            </div>
            <p className="text-sm font-semibold">Furnishing your room…</p>
            <p className="text-xs text-ink-soft">This takes about 30-60 seconds. You can keep planning meanwhile.</p>
            <Button variant="ghost" size="sm" onClick={() => { abortRef.current?.abort(); setPhase({ kind: "idle" }); }}>
              Cancel
            </Button>
          </div>
        ) : phase.kind === "done" ? (
          <div className="space-y-3">
            {/* eslint-disable-next-line @next/next/no-img-element -- generated data URL */}
            <img src={phase.image} alt="AI render of your furnished room" className="w-full rounded-lg border border-line" />
            <div className="flex flex-wrap items-center gap-2">
              <a href={phase.image} download="zory-room-preview.png">
                <Button variant="secondary" size="sm">
                  <Download className="h-3.5 w-3.5" />
                  Download
                </Button>
              </a>
              <Button variant="ghost" size="sm" onClick={() => void start()}>
                <RotateCcw className="h-3.5 w-3.5" />
                Regenerate
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 rounded-lg border border-danger/25 bg-danger-soft p-5 text-center">
            <p className="text-sm font-semibold text-danger">
              {phase.code === "RENDER_DISABLED" ? "AI preview is not configured on the backend." : phase.message}
            </p>
            <Button variant="secondary" size="sm" onClick={() => void start()}>
              <RotateCcw className="h-3.5 w-3.5" />
              Try again
            </Button>
          </div>
        )}
      </div>
    </Dialog>
  );
}
