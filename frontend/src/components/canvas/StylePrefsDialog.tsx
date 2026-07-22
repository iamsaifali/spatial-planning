"use client";

import { useEffect } from "react";
import { Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { COLOR_FAMILIES, FAMILY_SWATCH, STYLES, styleLabel } from "@/lib/styleMetadata";
import {
  LIVING_ROOM_PIECES,
  SEAT_COUNT_MAX,
  SEAT_COUNT_MIN,
  SOFA_TYPE_OPTIONS,
  defaultIncludedPieces,
  type SofaType,
} from "@/lib/pieces";
import { usePrefsStore } from "@/stores/prefsStore";
import type { Preferences } from "@/types/api";

const DEFAULT_SEAT_COUNT = 4;

/** "Pick your style" step shown when the user hits "Assist with AI". Captures a single style and any
 *  number of colour families, which are REQUIRED before generating. For living rooms it also captures
 *  seat count, the main-sofa footprint, and a piece checklist (backend gates these to living rooms).
 *  Fully store-controlled (each pick is written straight to Preferences) so the selection survives
 *  re-renders; onConfirm then runs the assist, which reads the prefs back out of the store. */
export function StylePrefsDialog({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const style = usePrefsStore((s) => s.preferences.style ?? null);
  const families = usePrefsStore((s) => s.preferences.color_families ?? []);
  const roomType = usePrefsStore((s) => s.preferences.room_type ?? null);
  const seatCount = usePrefsStore((s) => s.preferences.seating_capacity ?? null);
  const sofaType = usePrefsStore((s) => s.preferences.sofa_type ?? "auto");
  const includedPieces = usePrefsStore((s) => s.preferences.included_pieces ?? null);
  const setPreferences = usePrefsStore((s) => s.setPreferences);

  // The living-room extras (seats / sofa / pieces) only apply to living rooms; a bedroom keeps the
  // plain style+colour flow (the backend ignores these fields there).
  const isLivingRoom = roomType === null || roomType === "living_room";

  const patch = (p: Partial<Preferences>) =>
    setPreferences({ ...usePrefsStore.getState().preferences, ...p });

  // Seed the living-room defaults once the dialog opens: essentials pre-checked, 4 seats, auto sofa.
  // Only fill fields that are unset so a user's earlier explicit choices are never clobbered.
  useEffect(() => {
    if (!open || !isLivingRoom) return;
    const prefs = usePrefsStore.getState().preferences;
    const seed: Partial<Preferences> = {};
    if (prefs.included_pieces == null) seed.included_pieces = defaultIncludedPieces();
    if (prefs.seating_capacity == null) seed.seating_capacity = DEFAULT_SEAT_COUNT;
    if (prefs.sofa_type == null) seed.sofa_type = "auto";
    if (Object.keys(seed).length > 0) setPreferences({ ...prefs, ...seed });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isLivingRoom]);

  const pickStyle = (s: string) => patch({ style: style === s ? null : s });
  const toggleFamily = (f: string) =>
    patch({ color_families: families.includes(f) ? families.filter((x) => x !== f) : [...families, f] });

  const seats = seatCount ?? DEFAULT_SEAT_COUNT;
  const setSeats = (n: number) =>
    patch({ seating_capacity: Math.min(SEAT_COUNT_MAX, Math.max(SEAT_COUNT_MIN, n)) });

  const pickSofa = (value: SofaType) => patch({ sofa_type: value });

  const checked = includedPieces ?? defaultIncludedPieces();
  const togglePiece = (key: string) =>
    patch({
      included_pieces: checked.includes(key) ? checked.filter((k) => k !== key) : [...checked, key],
    });

  const canGenerate = style !== null && families.length > 0;
  const generate = () => {
    if (canGenerate) onConfirm();
  };

  return (
    <Dialog open={open} onClose={onClose} title="Pick your style">
      <div className="space-y-4">
        <p className="text-xs leading-5 text-ink-soft">
          Choose a look and the colours you like — we&apos;ll build layouts with matching products.
        </p>

        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Style</p>
          <div className="flex flex-wrap gap-1.5">
            {STYLES.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => pickStyle(s)}
                aria-pressed={style === s}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  style === s
                    ? "border-ink bg-ink text-surface"
                    : "border-line bg-surface text-ink hover:border-ink-faint"
                }`}
              >
                {styleLabel(s)}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
            Colours <span className="font-normal normal-case text-ink-faint">(pick any)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {COLOR_FAMILIES.map((f) => {
              const on = families.includes(f);
              return (
                <button
                  key={f}
                  type="button"
                  onClick={() => toggleFamily(f)}
                  aria-pressed={on}
                  className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    on ? "border-ink bg-surface-2 text-ink" : "border-line bg-surface text-ink hover:border-ink-faint"
                  }`}
                >
                  <span
                    className="h-3.5 w-3.5 rounded-full border border-black/10"
                    style={{ backgroundColor: FAMILY_SWATCH[f] }}
                    aria-hidden
                  />
                  {f}
                </button>
              );
            })}
          </div>
        </div>

        {isLivingRoom && (
          <>
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Number of seats
              </p>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setSeats(seats - 1)}
                  disabled={seats <= SEAT_COUNT_MIN}
                  aria-label="Fewer seats"
                  className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-surface text-ink transition-colors hover:border-ink-faint disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Minus className="h-4 w-4" />
                </button>
                <span className="min-w-6 text-center text-sm font-semibold tabular-nums text-ink">
                  {seats}
                </span>
                <button
                  type="button"
                  onClick={() => setSeats(seats + 1)}
                  disabled={seats >= SEAT_COUNT_MAX}
                  aria-label="More seats"
                  className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-surface text-ink transition-colors hover:border-ink-faint disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Plus className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Main sofa
              </p>
              <div className="flex flex-wrap gap-1.5">
                {SOFA_TYPE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => pickSofa(opt.value)}
                    aria-pressed={sofaType === opt.value}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      sofaType === opt.value
                        ? "border-ink bg-ink text-surface"
                        : "border-line bg-surface text-ink hover:border-ink-faint"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Pieces to include
              </p>
              {(["essential", "optional"] as const).map((tier) => {
                const rows = LIVING_ROOM_PIECES.filter((p) => p.tier === tier);
                if (rows.length === 0) return null;
                return (
                  <div key={tier} className="mb-2 last:mb-0">
                    <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
                      {tier === "essential" ? "Essential" : "Add more"}
                    </p>
                    <div className="grid grid-cols-2 gap-1.5">
                      {rows.map((piece) => {
                        const Icon = piece.icon;
                        const on = checked.includes(piece.key);
                        return (
                          <button
                            key={piece.key}
                            type="button"
                            onClick={() => togglePiece(piece.key)}
                            aria-pressed={on}
                            className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-xs transition-colors ${
                              on
                                ? "border-ink bg-surface-2 text-ink"
                                : "border-line bg-surface text-ink-soft hover:border-ink-faint"
                            }`}
                          >
                            <Icon className="h-4 w-4 shrink-0" aria-hidden />
                            <span className="truncate">{piece.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        <div className="flex items-center justify-between gap-2 pt-1">
          <p className="text-xs text-ink-faint">
            {canGenerate ? " " : "Pick a style and at least one colour to continue."}
          </p>
          <Button variant="primary" size="sm" disabled={!canGenerate} onClick={generate}>
            Generate layouts
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
