"use client";

import { ArrowRightLeft, MapPin, RotateCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { removeItem, validateItemDebounced } from "@/lib/placement";
import { CATEGORY_LABELS } from "@/lib/constants";
import { useGuideStore, type StepKey } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";

/** Floating actions for the selected item: rotate / alternative spot / swap / delete.
 *  Doubles as the touch path for actions that otherwise need a keyboard. */
export function ItemActionsBar() {
  const selectedId = useUiStore((s) => s.selectedId);
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);
  const setGhost = useUiStore((s) => s.setGhost);
  const ghost = useUiStore((s) => s.ghost);
  const toast = useUiStore((s) => s.toast);
  const setCurrentStep = useGuideStore((s) => s.setCurrentStep);
  const [finding, setFinding] = useState(false);

  const item = items.find((i) => i.instance_id === selectedId);
  if (!item) return null;
  const product = byId[item.product_id];
  const name = item.custom?.name ?? product?.name ?? "Item";
  const category = item.custom ? "custom" : product?.category;

  const rotate = () => {
    usePlannerStore.getState().moveItem(item.instance_id, {
      rotation_deg: (item.rotation_deg + 90) % 360,
    });
    validateItemDebounced(item.instance_id);
  };

  const alternativeSpot = async () => {
    if (finding) return;
    setFinding(true);
    try {
      const { room, items: placed } = usePlannerStore.getState();
      const others = placed.filter((i) => i.instance_id !== item.instance_id);
      const res = await api.suggestPlacement(room, others, item.product_id, null, usePrefsStore.getState().preferences);
      const moved =
        Math.hypot(res.pose.x - item.x, res.pose.y - item.y) > 20 ||
        res.pose.rotation_deg !== item.rotation_deg;
      const alt = moved ? res.pose : res.alternatives[0];
      if (!alt) {
        toast("info", "This is already the best spot I can find.");
        return;
      }
      setGhost({ productId: item.product_id, pose: alt, label: "Alternative spot" });
    } catch {
      toast("error", "Couldn't compute an alternative spot.");
    } finally {
      setFinding(false);
    }
  };

  const applyGhostPose = () => {
    const g = useUiStore.getState().ghost;
    if (!g) return;
    usePlannerStore.getState().moveItem(item.instance_id, g.pose);
    setGhost(null);
    validateItemDebounced(item.instance_id);
  };

  return (
    <div className="pointer-events-auto flex max-w-[calc(100vw-16px)] items-center gap-1 overflow-x-auto rounded-full border border-line bg-surface px-2 py-1.5 shadow-pop">
      <span className="max-w-36 truncate px-1.5 text-xs font-semibold" title={name}>
        {name}
      </span>
      <span className="h-4 w-px shrink-0 bg-line" aria-hidden />
      <ActionButton label="Rotate 90°" onClick={rotate}>
        <RotateCw className="h-3.5 w-3.5" />
      </ActionButton>
      {item.custom == null && (
        <>
          <ActionButton label="Alternative spot" onClick={() => void alternativeSpot()} busy={finding}>
            <MapPin className="h-3.5 w-3.5" />
          </ActionButton>
          {category && category !== "custom" && (
            <ActionButton
              label={`Swap ${CATEGORY_LABELS[category].toLowerCase()}`}
              onClick={() => {
                setCurrentStep(category as StepKey);
                useUiStore.getState().setSheet("guideSheetOpen", false);
                toast("info", `Pick a replacement from the ${CATEGORY_LABELS[category]} recommendations.`);
              }}
            >
              <ArrowRightLeft className="h-3.5 w-3.5" />
            </ActionButton>
          )}
        </>
      )}
      {ghost && (
        <button
          onClick={applyGhostPose}
          className="shrink-0 rounded-full bg-success px-3 py-1.5 text-[11px] font-semibold text-white"
        >
          Use spot
        </button>
      )}
      <ActionButton label="Delete" onClick={() => removeItem(item.instance_id)} danger>
        <Trash2 className="h-3.5 w-3.5" />
      </ActionButton>
    </div>
  );
}

function ActionButton({
  label,
  onClick,
  children,
  danger = false,
  busy = false,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  danger?: boolean;
  busy?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      disabled={busy}
      className={`flex h-8 shrink-0 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium disabled:opacity-50 ${
        danger ? "text-danger hover:bg-danger-soft" : "text-ink-soft hover:bg-surface-2 hover:text-ink"
      }`}
    >
      {children}
      <span className="hidden md:inline">{label}</span>
    </button>
  );
}
