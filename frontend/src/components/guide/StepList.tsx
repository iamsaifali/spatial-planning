"use client";

import { Check, Minus } from "lucide-react";
import { CATEGORY_LABELS } from "@/lib/constants";
import { STEP_ORDER, useGuideStore, type StepKey } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";

export type StepStatus = "done" | "current" | "current-done" | "pending" | "skipped";

export function useStepStatuses(): Record<StepKey, StepStatus> {
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);
  const skipped = useGuideStore((s) => s.skipped);
  const currentStepKey = useGuideStore((s) => s.currentStepKey);

  const placedCategories = new Set(items.map((i) => byId[i.product_id]?.category).filter(Boolean));
  const statuses = {} as Record<StepKey, StepStatus>;
  for (const key of STEP_ORDER) {
    const placed = placedCategories.has(key);
    if (key === currentStepKey) statuses[key] = placed ? "current-done" : "current";
    else if (placed) statuses[key] = "done";
    else if (skipped.has(key)) statuses[key] = "skipped";
    else statuses[key] = "pending";
  }
  return statuses;
}

export function StepList({ compact = false }: { compact?: boolean }) {
  const statuses = useStepStatuses();
  const setCurrentStep = useGuideStore((s) => s.setCurrentStep);

  return (
    <ol className={compact ? "flex flex-col items-center gap-1.5" : "space-y-0.5"} aria-label="Room building steps">
      {STEP_ORDER.map((key, index) => {
        const status = statuses[key];
        const isCurrent = status === "current" || status === "current-done";
        const isDone = status === "done" || status === "current-done";
        const isSkipped = status === "skipped";

        const badge = (
          <span
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
              status === "current-done"
                ? "bg-success text-white"
                : isCurrent
                  ? "bg-accent text-accent-ink"
                  : isDone
                    ? "bg-success-soft text-success"
                    : isSkipped
                      ? "bg-surface-2 text-ink-faint"
                      : "border border-line-strong bg-surface text-ink-soft"
            }`}
          >
            {isDone ? <Check className="h-3.5 w-3.5" /> : isSkipped ? <Minus className="h-3.5 w-3.5" /> : index + 1}
          </span>
        );

        if (compact) {
          return (
            <li key={key}>
              <button
                onClick={() => setCurrentStep(key)}
                title={CATEGORY_LABELS[key]}
                aria-label={`Step ${index + 1}: ${CATEGORY_LABELS[key]}`}
                aria-current={isCurrent ? "step" : undefined}
                className="rounded-full transition-transform hover:scale-110"
              >
                {badge}
              </button>
            </li>
          );
        }
        return (
          <li key={key}>
            <button
              onClick={() => setCurrentStep(key)}
              aria-current={isCurrent ? "step" : undefined}
              className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors ${
                isCurrent ? "bg-surface-2 font-semibold text-ink" : "text-ink-soft hover:bg-surface-2/70 hover:text-ink"
              }`}
            >
              {badge}
              <span className={isSkipped ? "line-through opacity-60" : ""}>{CATEGORY_LABELS[key]}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
