"use client";

import { Maximize2, Minus, Plus } from "lucide-react";
import { useUiStore } from "@/stores/uiStore";

export function ZoomControls() {
  const nudgeZoom = useUiStore((s) => s.nudgeZoom);
  const requestFit = useUiStore((s) => s.requestFit);
  const zoomPct = useUiStore((s) => s.zoomPct);

  return (
    <div className="pointer-events-auto flex flex-col items-center gap-0.5 rounded-full border border-line bg-surface p-1 shadow-soft">
      <button
        onClick={() => nudgeZoom(1)}
        title="Zoom in (+)"
        aria-label="Zoom in"
        className="flex h-9 w-9 items-center justify-center rounded-full text-ink-soft hover:bg-surface-2 hover:text-ink"
      >
        <Plus className="h-4 w-4" />
      </button>
      <span className="w-9 text-center text-[9px] font-bold text-ink-soft tabular-nums" aria-live="polite">
        {zoomPct}%
      </span>
      <button
        onClick={requestFit}
        title="Fit room (F)"
        aria-label="Fit room to view"
        className="flex h-9 w-9 items-center justify-center rounded-full text-ink-soft hover:bg-surface-2 hover:text-ink"
      >
        <Maximize2 className="h-4 w-4" />
      </button>
      <button
        onClick={() => nudgeZoom(-1)}
        title="Zoom out (−)"
        aria-label="Zoom out"
        className="flex h-9 w-9 items-center justify-center rounded-full text-ink-soft hover:bg-surface-2 hover:text-ink"
      >
        <Minus className="h-4 w-4" />
      </button>
    </div>
  );
}
