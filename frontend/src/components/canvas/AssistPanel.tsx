"use client";

import { Check, Info, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { StylePrefsDialog } from "./StylePrefsDialog";
import { acceptLayout, dismissLayout, previewLayout, requestLayout } from "@/lib/placement";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import type { AssistLayoutResponse, AssistTemplate, RoomType } from "@/types/api";

/** Cultural style tags dropped when (re)selecting a supported room type. `majlis` stays a
 *  product tag in the catalog, but is no longer a selectable planner room type. */
const CULTURAL_TAGS = new Set(["majlis", "arabic", "saudi_traditional", "modern_arabic", "luxury"]);

const ROOM_LABEL: Record<RoomType, string> = {
  living_room: "Living Room",
  majlis: "Saudi Majlis",
  bedroom: "Bedroom",
};

function applyRoomType(rt: RoomType) {
  const { preferences, setPreferences } = usePrefsStore.getState();
  // drop any cultural fields + cultural style tags.
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

/** Assist-with-AI entry point + ghost-proposal controls, rendered as an HTML overlay
 *  above the Konva canvas.
 *
 *  Backend (POST /assist/layout) is the source of truth for geometry; this panel only
 *  chooses the room type, triggers a proposal, and lets the user accept/dismiss the
 *  resulting ghosts. Image generation stays a separate, later step - accepting a
 *  layout simply turns ghosts into normal placed items. */
export function AssistPanel() {
  const proposedCount = usePlannerStore((s) => s.proposedItems.length);
  // clamp to a supported planner room type (a stale persisted "majlis" pref -> living_room)
  const roomType: RoomType = usePrefsStore((s) => (s.preferences.room_type === "bedroom" ? "bedroom" : "living_room"));

  const [loading, setLoading] = useState(false);
  const [prefsOpen, setPrefsOpen] = useState(false);
  const [templates, setTemplates] = useState<AssistTemplate[]>([]);
  const [selected, setSelected] = useState(0);

  const run = async () => {
    setLoading(true);
    try {
      const ts = await requestLayout();
      setTemplates(ts);
      const rec = ts.findIndex((t) => t.recommended);
      setSelected(rec >= 0 ? rec : 0);
    } finally {
      setLoading(false);
    }
  };

  const selectTemplate = (i: number) => {
    setSelected(i);
    previewLayout(templates[i].layout); // re-stage that template's ghosts on the canvas
  };

  const proposal: AssistLayoutResponse | null = templates[selected]?.layout ?? null;

  // --- entry state: room-type selector + Assist button ---------------------------
  if (proposedCount === 0) {
    return (
      <>
      <div className="pointer-events-none absolute left-1/2 top-3 z-20 -translate-x-1/2">
        <div className="pointer-events-auto flex items-center gap-2 rounded-2xl border border-line-strong bg-surface px-2 py-1.5 shadow-md">
          <RoomTypeToggle value={roomType} onChange={applyRoomType} />
          <Button variant="primary" size="sm" loading={loading} onClick={() => setPrefsOpen(true)}>
            {!loading && <Sparkles className="h-4 w-4" aria-hidden />}
            Assist with AI
          </Button>
        </div>
      </div>
      <StylePrefsDialog
        open={prefsOpen}
        onClose={() => setPrefsOpen(false)}
        onConfirm={() => {
          setPrefsOpen(false);
          void run();
        }}
      />
      </>
    );
  }

  // --- proposal state: template picker + controls + QA summary -------------------
  return (
    <div className="pointer-events-none absolute left-1/2 top-3 z-20 flex w-[min(94vw,620px)] -translate-x-1/2 flex-col items-center gap-2">
      {templates.length > 1 && (
        <div className="panel-scroll pointer-events-auto flex w-full gap-2 overflow-x-auto rounded-2xl border border-line-strong bg-surface px-2 py-2 shadow-md">
          {templates.map((t, i) => (
            <button
              key={t.label}
              onClick={() => selectTemplate(i)}
              aria-pressed={i === selected}
              className={`flex min-w-[140px] shrink-0 flex-col items-start gap-0.5 rounded-xl border px-3 py-2 text-left transition-colors ${
                i === selected
                  ? "border-accent bg-accent/10"
                  : "border-line bg-surface-2/40 hover:border-line-strong"
              }`}
            >
              <span className="flex items-center gap-1.5 text-xs font-semibold text-ink">
                {t.label}
                {t.recommended && (
                  <span className="rounded-full bg-accent px-1.5 py-[1px] text-[9px] font-bold text-accent-ink">
                    PICK
                  </span>
                )}
              </span>
              <span className="text-[11px] text-ink-soft">
                {t.layout.totals.item_count} items · {t.layout.totals.currency}{" "}
                {t.layout.totals.total_price.toLocaleString()}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="pointer-events-auto flex flex-wrap items-center justify-center gap-2 rounded-2xl border border-line-strong bg-surface px-3 py-2 shadow-md">
        <span className="px-1 text-sm font-medium text-ink">
          {templates.length > 1 ? "Pick a layout, then" : "Review, then"}
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
            setTemplates([]);
          }}
        >
          <X className="h-4 w-4" aria-hidden />
          Dismiss
        </Button>
      </div>
      {proposal && proposal.notices.length > 0 && <NoticesNote notices={proposal.notices} />}
      {proposal && <ProposalQA proposal={proposal} roomType={roomType} />}
    </div>
  );
}

/** Gentle, user-facing note listing the pieces the user included that couldn't be placed
 *  in the currently-selected layout. Reflects `proposal.notices`, so it updates whenever
 *  the user switches templates. Strings are display-ready from the backend - rendered as-is. */
function NoticesNote({ notices }: { notices: string[] }) {
  return (
    <div className="pointer-events-auto flex w-full items-start gap-2 rounded-2xl border border-amber-soft bg-amber-faint px-3 py-2 text-xs text-ink shadow-sm">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-deep" aria-hidden />
      <div>
        <span className="font-semibold text-amber-deep">Couldn&apos;t fit everything</span>
        <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-ink-soft">
          {notices.map((notice) => (
            <li key={notice}>{notice}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function RoomTypeToggle({ value, onChange }: { value: RoomType; onChange: (rt: RoomType) => void }) {
  return (
    <div className="flex items-center rounded-full bg-surface-2 p-0.5">
      {(["living_room", "bedroom"] as const).map((rt) => (
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
