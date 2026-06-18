"use client";

import { ArrowRight, PencilRuler, Sofa } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";

/** First-run choice: draw your own room, or start from the sample. The
 *  analyze -> plan -> recommend pipeline stays paused until one is chosen. */
export function RoomSetupDialog({
  open,
  onDrawOwn,
  onUseSample,
}: {
  open: boolean;
  onDrawOwn: () => void;
  onUseSample: () => void;
}) {
  return (
    <Dialog open={open} onClose={onDrawOwn} title="How do you want to start?">
      <div className="space-y-4">
        <p className="text-xs leading-5 text-ink-soft">
          Draw your own walls, or start from the sample room. ZORY only begins planning once your
          room is ready - nothing is recommended until you say go.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <button
            onClick={onDrawOwn}
            className="group flex flex-col rounded-lg border border-line bg-surface p-4 text-left transition-colors hover:border-amber"
          >
            <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-amber-soft text-amber-deep">
              <PencilRuler className="h-5 w-5" />
            </span>
            <p className="text-sm font-semibold">Draw my own room</p>
            <p className="mt-1 text-xs leading-5 text-ink-soft">
              Blank canvas - sketch the walls, then add doors &amp; windows. The wall tool is ready.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-amber-deep">
              Start drawing <ArrowRight className="h-3.5 w-3.5" />
            </span>
          </button>
          <button
            onClick={onUseSample}
            className="group flex flex-col rounded-lg border border-line bg-surface p-4 text-left transition-colors hover:border-amber"
          >
            <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-amber-soft text-amber-deep">
              <Sofa className="h-5 w-5" />
            </span>
            <p className="text-sm font-semibold">Use the sample room</p>
            <p className="mt-1 text-xs leading-5 text-ink-soft">
              A 4.8 &times; 3.6 m room with a door &amp; window - ZORY starts planning right away.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-amber-deep">
              Use sample <ArrowRight className="h-3.5 w-3.5" />
            </span>
          </button>
        </div>
        <p className="text-[11px] leading-4 text-ink-faint">
          Prefer a preset shape? Use the <span className="font-semibold">Templates</span> button on the
          canvas toolbar, then press Start planning.
        </p>
      </div>
    </Dialog>
  );
}
