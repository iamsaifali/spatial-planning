"use client";

import { Move3d, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useUiStore } from "@/stores/uiStore";
import { Skeleton } from "@/components/ui/Skeleton";

// three.js loads only when the dialog first opens
const Scene3D = dynamic(() => import("./Scene3D"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center">
      <Skeleton className="h-2/3 w-3/4" />
    </div>
  ),
});

export function View3DDialog() {
  const open = useUiStore((s) => s.view3DOpen);
  const setSheet = useUiStore((s) => s.setSheet);
  if (!open) return null;

  return (
    <div className="pointer-events-auto fixed inset-0 z-50 flex flex-col bg-bg" role="dialog" aria-modal="true" aria-label="3D room view">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-line bg-surface px-4">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <Move3d className="h-4 w-4 text-amber-deep" aria-hidden />
          Room in 3D
          <span className="hidden text-xs font-normal text-ink-soft sm:inline">
            · drag to orbit, scroll or pinch to zoom, right-drag to pan
          </span>
        </p>
        <button
          onClick={() => setSheet("view3DOpen", false)}
          aria-label="Close 3D view"
          className="rounded-full p-2 text-ink-soft hover:bg-surface-2 hover:text-ink"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="relative min-h-0 flex-1">
        <Scene3D />
      </div>
    </div>
  );
}
