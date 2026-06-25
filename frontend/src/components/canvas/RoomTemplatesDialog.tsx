"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { emptyRectRoom, lShapeRoom, sampleRoom } from "@/lib/constants";
import { usePlannerStore } from "@/stores/plannerStore";
import { useUiStore } from "@/stores/uiStore";

export function RoomTemplatesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const setRoom = usePlannerStore((s) => s.setRoom);
  const clearItems = usePlannerStore((s) => s.clearItems);
  const requestFit = useUiStore((s) => s.requestFit);
  const toast = useUiStore((s) => s.toast);
  const [w, setW] = useState(480);
  const [d, setD] = useState(360);

  const apply = (roomFactory: () => ReturnType<typeof sampleRoom>, label: string) => {
    setRoom(roomFactory());
    clearItems();
    requestFit();
    toast("success", `${label} loaded - placed items were cleared.`);
    onClose();
  };

  const applyCustomRect = () => {
    const width = Math.min(2900, Math.max(200, w));
    const depth = Math.min(2900, Math.max(200, d));
    apply(() => emptyRectRoom(width, depth), `${(width / 100).toFixed(1)} x ${(depth / 100).toFixed(1)} m room`);
  };

  return (
    <Dialog open={open} onClose={onClose} title="Start from a template">
      <div className="space-y-4">
        <p className="text-xs leading-5 text-ink-soft">
          Replacing the room clears placed furniture. You can also draw any shape with the wall tool.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => apply(sampleRoom, "Sample living room")}
            className="group rounded-lg border border-line bg-surface p-4 text-left hover:border-amber"
          >
            <div className="mx-auto mb-3 h-16 w-24 rounded-sm border-2 border-ink/70 bg-room transition-colors group-hover:border-amber-deep" />
            <p className="text-sm font-semibold">Sample room</p>
            <p className="text-xs text-ink-soft">4.8 × 3.6 m with door & window</p>
          </button>
          <button
            onClick={() => apply(lShapeRoom, "L-shaped room")}
            className="group rounded-lg border border-line bg-surface p-4 text-left hover:border-amber"
          >
            <div className="relative mx-auto mb-3 h-16 w-24">
              <div className="absolute inset-0 rounded-sm border-2 border-ink/70 bg-room transition-colors group-hover:border-amber-deep" />
              <div className="absolute right-0 bottom-0 h-8 w-10 border-t-2 border-l-2 border-ink/70 bg-bg transition-colors group-hover:border-amber-deep" />
            </div>
            <p className="text-sm font-semibold">L-shape</p>
            <p className="text-xs text-ink-soft">5.6 × 4.8 m overall</p>
          </button>
          <button
            onClick={() => apply(() => emptyRectRoom(800, 650), "Large room")}
            className="group rounded-lg border border-line bg-surface p-4 text-left hover:border-amber"
          >
            <div className="mx-auto mb-3 h-16 w-24 rounded-sm border-2 border-ink/70 bg-room transition-colors group-hover:border-amber-deep" />
            <p className="text-sm font-semibold">Large room</p>
            <p className="text-xs text-ink-soft">8.0 × 6.5 m — shows a 2nd seating zone</p>
          </button>
        </div>

        <div className="rounded-lg border border-line bg-surface-2/60 p-4">
          <p className="mb-3 text-sm font-semibold">Custom rectangle</p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-ink-soft">
              Width (cm)
              <input
                type="number"
                value={w}
                min={200}
                max={2900}
                onChange={(e) => setW(Number(e.target.value))}
                className="mt-1 block w-28 rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
              />
            </label>
            <label className="text-xs text-ink-soft">
              Depth (cm)
              <input
                type="number"
                value={d}
                min={200}
                max={2900}
                onChange={(e) => setD(Number(e.target.value))}
                className="mt-1 block w-28 rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
              />
            </label>
            <Button variant="secondary" size="md" onClick={applyCustomRect}>
              Create room
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
