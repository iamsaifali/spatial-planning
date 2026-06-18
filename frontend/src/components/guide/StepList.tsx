"use client";

import { Check, Minus } from "lucide-react";
import { CATEGORY_LABELS } from "@/lib/constants";
import { useGuideStore, type StepKey } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";

export function StepList({ compact = false }: { compact?: boolean }) {
  const planSteps = useGuideStore((s) => s.planSteps);
  const currentStepKey = useGuideStore((s) => s.currentStepKey);
  const setCurrentStep = useGuideStore((s) => s.setCurrentStep);
  const skipped = useGuideStore((s) => s.skipped);
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);

  const counts: Record<string, number> = {};
  for (const it of items) {
    const cat = byId[it.product_id]?.category;
    if (cat) counts[cat] = (counts[cat] ?? 0) + 1;
  }

  return (
    <ol className={compact ? "flex flex-col items-center gap-1.5" : "space-y-0.5"} aria-label="Room building steps">
      {planSteps.map((step, index) => {
        const placedN = Math.min(counts[step.category] ?? 0, step.quantity);
        const isDone = placedN >= step.quantity;
        const isCurrent = step.key === currentStepKey;
        const isSkipped = !isDone && skipped.has(step.key);
        const currentDone = isCurrent && isDone;
        const label = CATEGORY_LABELS[step.category];
        const qtySuffix = step.quantity > 1 ? ` (${placedN}/${step.quantity})` : "";

        const badge = (
          <span
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
              currentDone
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
            <li key={step.key}>
              <button
                onClick={() => setCurrentStep(step.category as StepKey)}
                title={label}
                aria-label={`Step ${index + 1}: ${label}`}
                aria-current={isCurrent ? "step" : undefined}
                className="rounded-full transition-transform hover:scale-110"
              >
                {badge}
              </button>
            </li>
          );
        }
        return (
          <li key={step.key}>
            <button
              onClick={() => setCurrentStep(step.category as StepKey)}
              aria-current={isCurrent ? "step" : undefined}
              className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors ${
                isCurrent ? "bg-surface-2 font-semibold text-ink" : "text-ink-soft hover:bg-surface-2/70 hover:text-ink"
              }`}
            >
              {badge}
              <span className={isSkipped ? "line-through opacity-60" : ""}>
                {label}
                {qtySuffix}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
