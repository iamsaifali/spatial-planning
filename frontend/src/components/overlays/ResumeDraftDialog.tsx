"use client";

import { History, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import type { PlacedItem, Room } from "@/types/api";

export interface PendingDraft {
  room: Room;
  items: PlacedItem[];
  savedAt?: number;
}

function describe(draft: PendingDraft): string {
  const xs = draft.room.vertices.map((v) => v[0]);
  const ys = draft.room.vertices.map((v) => v[1]);
  const w = ((Math.max(...xs) - Math.min(...xs)) / 100).toFixed(1);
  const d = ((Math.max(...ys) - Math.min(...ys)) / 100).toFixed(1);
  const items = draft.items.length;
  return `${w} × ${d} m room · ${items} item${items !== 1 ? "s" : ""} placed`;
}

function relativeTime(ts?: number): string | null {
  if (!ts) return null;
  const mins = Math.round((Date.now() - ts) / 60_000);
  if (mins < 1) return "moments ago";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours > 1 ? "s" : ""} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days > 1 ? "s" : ""} ago`;
}

/** Load-time choice: pick up the saved draft or begin a brand-new room. */
export function ResumeDraftDialog({
  draft,
  onContinue,
  onStartFresh,
}: {
  draft: PendingDraft | null;
  onContinue: () => void;
  onStartFresh: () => void;
}) {
  if (!draft) return null;
  const when = relativeTime(draft.savedAt);

  return (
    <Dialog open onClose={onContinue} title="Welcome back">
      <div className="space-y-4">
        <p className="text-sm leading-6 text-ink-soft">
          You have an unsaved room from last time
          {when ? ` (edited ${when})` : ""}:
        </p>
        <div className="flex items-center gap-3 rounded-lg border border-line bg-surface-2/60 px-4 py-3">
          <History className="h-5 w-5 shrink-0 text-amber-deep" aria-hidden />
          <p className="text-sm font-semibold">{describe(draft)}</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button size="lg" className="flex-1" onClick={onContinue}>
            <History className="h-4 w-4" />
            Continue where I left off
          </Button>
          <Button size="lg" variant="secondary" className="flex-1" onClick={onStartFresh}>
            <Sparkles className="h-4 w-4" />
            Start fresh
          </Button>
        </div>
        <p className="text-[11px] leading-4 text-ink-faint">
          Starting fresh clears the draft room and its items. Your cart, favourites and
          preferences are kept. You can also reset anytime via the Templates tool.
        </p>
      </div>
    </Dialog>
  );
}
