"use client";

import { Check, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { acceptLayout, dismissLayout, requestLayout } from "@/lib/placement";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import type { AssistLayoutResponse, Preferences, RoomType } from "@/types/api";

/** Preference bundle applied when the user picks "Saudi Majlis" (mirrors the values
 *  the backend Majlis flow expects). Living Room clears these again. */
const MAJLIS_PRESET: Partial<Preferences> = {
  room_type: "majlis",
  styles: ["majlis", "arabic", "saudi_traditional"],
  region: "saudi_arabia",
  room_purpose: "entertaining",
  formality: "formal",
  luxury_tier: "premium",
};
const CULTURAL_TAGS = new Set(["majlis", "arabic", "saudi_traditional", "modern_arabic", "luxury"]);

const ROOM_LABEL: Record<RoomType, string> = {
  living_room: "Living Room",
  majlis: "Saudi Majlis",
  bedroom: "Bedroom",
};

function applyRoomType(rt: RoomType) {
  const { preferences, setPreferences } = usePrefsStore.getState();
  if (rt === "majlis") {
    setPreferences({ ...preferences, ...MAJLIS_PRESET, seating_capacity: preferences.seating_capacity ?? 8 });
  } else {
    // living room or bedroom: drop the cultural fields + cultural style tags.
    // room_type=null means living_room (the backend default); "bedroom" is explicit.
    setPreferences({
      ...preferences,
      room_type: rt === "bedroom" ? "bedroom" : null,
      region: null,
      formality: null,
      luxury_tier: null,
      seating_capacity: null,
      styles: preferences.styles.filter((s) => !CULTURAL_TAGS.has(s)),
    });
  }
}

/** Assist-with-AI entry point + ghost-proposal controls, rendered as an HTML overlay
 *  above the Konva canvas.
 *
 *  Backend (POST /assist/layout) is the source of truth for geometry; this panel only
 *  chooses the room type, triggers a proposal, and lets the user accept/dismiss the
 *  resulting ghosts. Image generation stays a separate, later step - accepting a
 *  layout simply turns ghosts into normal placed items. */
export function AssistPanel() {
  const proposedCount = usePlannerStore((s) => s.proposedItems.length);
  const roomType: RoomType = usePrefsStore((s) => s.preferences.room_type) ?? "living_room";
  const seats = usePrefsStore((s) => s.preferences.seating_capacity);
  const setPreferences = usePrefsStore((s) => s.setPreferences);

  const [loading, setLoading] = useState(false);
  const [proposal, setProposal] = useState<AssistLayoutResponse | null>(null);

  const run = async () => {
    setLoading(true);
    try {
      setProposal(await requestLayout());
    } finally {
      setLoading(false);
    }
  };

  // --- entry state: room-type selector + Assist button ---------------------------
  if (proposedCount === 0) {
    const isMajlis = roomType === "majlis";
    return (
      <div className="pointer-events-none absolute left-1/2 top-3 z-20 -translate-x-1/2">
        <div className="pointer-events-auto flex items-center gap-2 rounded-2xl border border-line-strong bg-surface px-2 py-1.5 shadow-md">
          <RoomTypeToggle value={roomType} onChange={applyRoomType} />
          {isMajlis && (
            <label className="flex items-center gap-1 text-xs text-ink-soft">
              Seats
              <input
                type="number"
                min={2}
                max={20}
                value={seats ?? ""}
                placeholder="8"
                onChange={(e) =>
                  setPreferences({
                    ...usePrefsStore.getState().preferences,
                    seating_capacity: e.target.value ? Number(e.target.value) : null,
                  })
                }
                className="w-14 rounded-md border border-line bg-surface px-2 py-1 text-sm"
                aria-label="Target seating capacity"
              />
            </label>
          )}
          <Button variant="primary" size="sm" loading={loading} onClick={run}>
            {!loading && <Sparkles className="h-4 w-4" aria-hidden />}
            Assist with AI
          </Button>
        </div>
      </div>
    );
  }

  // --- proposal state: controls + QA/debug summary -------------------------------
  return (
    <div className="pointer-events-none absolute left-1/2 top-3 z-20 flex w-[min(92vw,540px)] -translate-x-1/2 flex-col items-center gap-2">
      <div className="pointer-events-auto flex flex-wrap items-center justify-center gap-2 rounded-2xl border border-line-strong bg-surface px-3 py-2 shadow-md">
        <span className="px-1 text-sm font-medium text-ink">
          {proposedCount} suggestion{proposedCount > 1 ? "s" : ""} · tap one or…
        </span>
        <Button variant="amber" size="sm" onClick={acceptLayout}>
          <Check className="h-4 w-4" aria-hidden />
          Accept all
        </Button>
        <Button variant="secondary" size="sm" loading={loading} onClick={run}>
          {!loading && <RotateCcw className="h-4 w-4" aria-hidden />}
          Regenerate
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            dismissLayout();
            setProposal(null);
          }}
        >
          <X className="h-4 w-4" aria-hidden />
          Dismiss
        </Button>
      </div>
      {proposal && <ProposalQA proposal={proposal} roomType={roomType} />}
    </div>
  );
}

function RoomTypeToggle({ value, onChange }: { value: RoomType; onChange: (rt: RoomType) => void }) {
  return (
    <div className="flex items-center rounded-full bg-surface-2 p-0.5">
      {(["living_room", "majlis", "bedroom"] as const).map((rt) => (
        <button
          key={rt}
          onClick={() => onChange(rt)}
          aria-pressed={value === rt}
          className={`rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ${
            value === rt ? "bg-accent text-accent-ink" : "text-ink-soft hover:text-ink"
          }`}
        >
          {ROOM_LABEL[rt]}
        </button>
      ))}
    </div>
  );
}

/** QA / debug summary of the current proposal. */
function ProposalQA({ proposal, roomType }: { proposal: AssistLayoutResponse; roomType: RoomType }) {
  const totalSeats = proposal.placements.reduce((n, p) => n + (p.product.seating_capacity || 0), 0);
  const { totals, skipped, findings } = proposal;
  return (
    <div className="pointer-events-auto w-full rounded-2xl border border-line bg-surface/95 px-3 py-2 text-xs text-ink-soft shadow-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>
          <b className="text-ink">Room:</b> {ROOM_LABEL[roomType]}
        </span>
        <span>
          <b className="text-ink">Items:</b> {totals.item_count}
        </span>
        <span>
          <b className="text-ink">Seats:</b> {totalSeats}
        </span>
        <span>
          <b className="text-ink">Est.:</b> {totals.currency} {totals.total_price.toLocaleString()}
        </span>
      </div>
      {skipped.length > 0 && (
        <div className="mt-1">
          <b className="text-ink">Skipped:</b> {skipped.map((s) => `${s.category} (${s.reason})`).join(", ")}
        </div>
      )}
      {findings.length > 0 && (
        <div className="mt-1 text-amber-deep">
          <b>Warnings:</b> {findings.map((f) => f.code).join(", ")}
        </div>
      )}
    </div>
  );
}
