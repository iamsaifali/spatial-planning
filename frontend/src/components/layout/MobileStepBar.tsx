"use client";

import { ChevronUp, ShoppingCart } from "lucide-react";
import { CATEGORY_LABELS } from "@/lib/constants";
import { useMoney } from "@/lib/format";
import { useGuideStore } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import { useRoomTotal } from "./BottomBar";

/** Phone-only bottom bar: step pill (opens the guide sheet) + total + cart. */
export function MobileStepBar() {
  const currentStepKey = useGuideStore((s) => s.currentStepKey);
  const planSteps = useGuideStore((s) => s.planSteps);
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);
  const setSheet = useUiStore((s) => s.setSheet);
  const { total } = useRoomTotal();
  const money = useMoney();

  const counts: Record<string, number> = {};
  for (const i of items) {
    const c = byId[i.product_id]?.category;
    if (c) counts[c] = (counts[c] ?? 0) + 1;
  }
  const doneCount = planSteps.filter((s) => (counts[s.category] ?? 0) >= s.quantity).length;
  const stepNumber = planSteps.findIndex((s) => s.key === currentStepKey) + 1;

  return (
    <footer className="flex shrink-0 items-center gap-2 border-t border-line bg-surface px-3 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] md:hidden">
      <button
        onClick={() => setSheet("guideSheetOpen", true)}
        className="flex min-w-0 flex-1 items-center gap-2.5 rounded-full bg-accent px-3.5 py-2 text-left text-accent-ink"
        aria-label={`Open guide - step ${stepNumber}: ${CATEGORY_LABELS[currentStepKey]}`}
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber text-[11px] font-bold text-white">
          {stepNumber}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-semibold leading-4">{CATEGORY_LABELS[currentStepKey]}</span>
          <span className="block text-[10px] leading-3 opacity-70">{doneCount}/{planSteps.length} placed</span>
        </span>
        <ChevronUp className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
      </button>

      <div className="text-right">
        <p className="text-[9px] font-semibold uppercase tracking-wider text-ink-faint">Total</p>
        <p className="text-xs font-bold leading-4">{money(total)}</p>
      </div>
      <button
        onClick={() => setSheet("cartOpen", true)}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line text-ink-soft"
        aria-label="Open cart"
      >
        <ShoppingCart className="h-4.5 w-4.5" />
      </button>
    </footer>
  );
}
