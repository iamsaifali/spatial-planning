"use client";

import { ArrowLeftRight, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { DOOR_WIDTH_PRESETS, WINDOW_WIDTH_PRESETS } from "@/lib/constants";
import { wallLength } from "@/lib/geometry";
import { usePlannerStore } from "@/stores/plannerStore";
import { useUiStore } from "@/stores/uiStore";
import type { DoorSwing } from "@/types/api";

const SWING_LABELS: Record<DoorSwing, string> = {
  inward: "Opens in",
  outward: "Opens out",
  sliding: "Sliding",
  opening_only: "Open arch",
};

/** Floating editor card for the selected door/window. */
export function OpeningEditor() {
  const selectedOpeningId = useUiStore((s) => s.selectedOpeningId);
  const selectOpening = useUiStore((s) => s.selectOpening);
  const room = usePlannerStore((s) => s.room);
  const updateDoor = usePlannerStore((s) => s.updateDoor);
  const updateWindow = usePlannerStore((s) => s.updateWindow);
  const removeOpening = usePlannerStore((s) => s.removeOpening);

  if (!selectedOpeningId) return null;
  const door = room.doors.find((d) => d.id === selectedOpeningId);
  const win = door ? undefined : room.windows.find((w) => w.id === selectedOpeningId);
  if (!door && !win) return null;

  const opening = (door ?? win)!;
  const wallLen = wallLength(room, opening.wall_index);
  const presets = door ? DOOR_WIDTH_PRESETS : WINDOW_WIDTH_PRESETS;

  const setWidth = (width: number) => {
    const clamped = Math.min(width, Math.floor(wallLen));
    const offset = Math.min(opening.offset_cm, Math.max(0, wallLen - clamped));
    if (door) updateDoor(door.id, { width_cm: clamped, offset_cm: offset });
    else if (win) updateWindow(win.id, { width_cm: clamped, offset_cm: offset });
  };

  return (
    <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 shadow-pop">
      <span className="text-xs font-semibold">{door ? "Door" : "Window"}</span>
      <span className="h-4 w-px bg-line" aria-hidden />
      {presets.map((w) => (
        <button
          key={w}
          onClick={() => setWidth(w)}
          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
            opening.width_cm === w ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-surface-2"
          }`}
        >
          {w} cm
        </button>
      ))}
      {door && (
        <>
          <span className="h-4 w-px bg-line" aria-hidden />
          <select
            value={door.swing}
            onChange={(e) => updateDoor(door.id, { swing: e.target.value as DoorSwing })}
            className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-medium text-ink"
            aria-label="Door swing"
          >
            {Object.entries(SWING_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => updateDoor(door.id, { hinge: door.hinge === "left" ? "right" : "left" })}
            title="Flip hinge side"
          >
            <ArrowLeftRight className="h-3.5 w-3.5" />
            Hinge
          </Button>
        </>
      )}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          removeOpening(opening.id);
          selectOpening(null);
        }}
        title="Delete"
        className="text-danger hover:text-danger"
      >
        <Trash2 className="h-3.5 w-3.5" />
        Remove
      </Button>
    </div>
  );
}
