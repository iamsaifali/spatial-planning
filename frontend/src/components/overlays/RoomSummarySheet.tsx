"use client";

import { AlertTriangle, ArrowUpRight, Camera, CircleCheck, Move3d, ShoppingCart } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { ProductImage } from "@/components/ui/ProductImage";
import { Sheet } from "@/components/ui/Sheet";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import { savingsOf, useMoney } from "@/lib/format";
import { addAllToCart } from "@/components/layout/BottomBar";
import { useCartStore } from "@/stores/cartStore";
import { useCurrencyStore } from "@/stores/currencyStore";
import { useGuideStore, type StepKey } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useUiStore } from "@/stores/uiStore";
import type { SummaryResponse } from "@/types/api";

export function RoomSummarySheet() {
  const open = useUiStore((s) => s.summaryOpen);
  const setSheet = useUiStore((s) => s.setSheet);
  const toast = useUiStore((s) => s.toast);
  const setCurrentStep = useGuideStore((s) => s.setCurrentStep);
  const addToCart = useCartStore((s) => s.add);

  const money = useMoney();
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // reset stale results the moment the sheet re-opens (adjust during render)
  const [prevOpen, setPrevOpen] = useState(open);
  if (prevOpen !== open) {
    setPrevOpen(open);
    if (open) {
      setSummary(null);
      setError(null);
    }
  }

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const { room, items } = usePlannerStore.getState();
    const prefs = usePrefsStore.getState().preferences;
    const currency = useCurrencyStore.getState().currency;
    api
      .summary(room, items, prefs, currency)
      .then((res) => {
        if (!cancelled) setSummary(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't build the summary.");
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const loading = open && !summary && !error;

  const close = () => setSheet("summaryOpen", false);

  return (
    <Sheet open={open} onClose={close} title="Room summary" widthClass="sm:max-w-lg"
      footer={
        summary && summary.items.length > 0 ? (
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-faint">Total</p>
              <p className="truncate text-base font-bold">
                {money(summary.total_price)}
                {(() => {
                  const { save, pct } = savingsOf(summary.items.map((l) => l.product));
                  return save > 0 ? (
                    <span className="ml-1.5 text-[11px] font-semibold text-success">
                      saves {money(save)} ({pct}%)
                    </span>
                  ) : null;
                })()}
              </p>
            </div>
            <Button
              variant="secondary"
              size="md"
              aria-label="View room in 3D"
              onClick={() => { close(); setSheet("view3DOpen", true); }}
            >
              <Move3d className="h-4 w-4" />
              <span className="hidden sm:inline">3D</span>
            </Button>
            <Button
              variant="secondary"
              size="md"
              aria-label="AI photo preview"
              onClick={() => { close(); setSheet("renderOpen", true); }}
            >
              <Camera className="h-4 w-4" />
              <span className="hidden sm:inline">Preview</span>
            </Button>
            <Button
              size="md"
              onClick={() => {
                const n = addAllToCart();
                toast("success", `${n} item${n > 1 ? "s" : ""} added to cart.`);
                close();
                setSheet("cartOpen", true);
              }}
            >
              <ShoppingCart className="h-4 w-4" />
              Add all to cart
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="space-y-5 p-4">
        {loading && (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {error && <p className="rounded-md bg-danger-soft p-3 text-xs text-danger">{error}</p>}

        {summary && !loading && (
          <>
            {/* completeness */}
            <div className="flex items-center gap-4 rounded-lg border border-line bg-surface-2/60 p-4">
              <CompletenessRing pct={summary.completeness_pct} />
              <div className="min-w-0">
                <p className="text-sm font-bold">{summary.completeness_pct}% furnished</p>
                <p className="mt-0.5 text-xs leading-5 text-ink-soft">{summary.narrative.text}</p>
              </div>
            </div>

            {/* layout issues */}
            {summary.layout_findings.length > 0 && (
              <div className="flex items-start gap-2 rounded-md border border-warn/25 bg-warn-soft p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
                <p className="text-xs leading-5 text-warn">
                  {summary.layout_findings.length} placement note
                  {summary.layout_findings.length > 1 ? "s" : ""} - select items on the canvas to review.
                </p>
              </div>
            )}

            {/* items */}
            {summary.items.length === 0 ? (
              <p className="rounded-md bg-surface-2 p-4 text-center text-xs text-ink-soft">
                Nothing placed yet - follow the guide to build your room.
              </p>
            ) : (
              <section>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-soft">
                  In your room ({summary.items.length})
                </h3>
                <ul className="divide-y divide-line rounded-lg border border-line">
                  {summary.items.map((line) => (
                    <li key={line.instance_id} className="flex items-center gap-3 p-2.5">
                      <ProductImage src={line.product.image_url} alt="" className="h-11 w-11 shrink-0 rounded-md" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-semibold">{line.product.name}</p>
                        <p className="text-[10px] text-ink-faint">{line.product.brand}</p>
                      </div>
                      <p className="text-xs font-bold">{money(line.line_price)}</p>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* missing essentials */}
            {summary.missing_essentials.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-soft">Still missing</h3>
                <ul className="space-y-1.5">
                  {summary.missing_essentials.map((missing) => (
                    <li key={missing.category}>
                      <button
                        onClick={() => {
                          setCurrentStep(missing.category as StepKey);
                          close();
                        }}
                        className="flex w-full items-center justify-between gap-2 rounded-md border border-line bg-surface px-3 py-2 text-left hover:border-amber"
                      >
                        <span>
                          <span className="block text-xs font-semibold">{missing.label}</span>
                          <span className="block text-[11px] text-ink-soft">{missing.reason}</span>
                        </span>
                        <ArrowUpRight className="h-4 w-4 shrink-0 text-amber-deep" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* upgrades */}
            {summary.suggested_upgrades.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-soft">Worth upgrading</h3>
                <ul className="space-y-2">
                  {summary.suggested_upgrades.map((upgrade) => (
                    <li key={upgrade.from_product_id} className="flex items-center gap-3 rounded-lg border border-line p-2.5">
                      <ProductImage src={upgrade.to_product.image_url} alt="" className="h-11 w-11 shrink-0 rounded-md" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-semibold">{upgrade.to_product.name}</p>
                        <p className="text-[10px] leading-4 text-ink-soft">{upgrade.reason}</p>
                        <Chip tone="amber" className="mt-1">+{money(upgrade.delta)}</Chip>
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          addToCart(upgrade.to_product);
                          toast("success", `${upgrade.to_product.name} added to cart.`);
                        }}
                      >
                        Add
                      </Button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {summary.completeness_pct === 100 && (
              <p className="flex items-center gap-2 rounded-md bg-success-soft p-3 text-xs font-medium text-success">
                <CircleCheck className="h-4 w-4" /> All essentials placed - your room is complete.
              </p>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}

function CompletenessRing({ pct }: { pct: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  return (
    <svg width="68" height="68" viewBox="0 0 68 68" role="img" aria-label={`${pct} percent complete`} className="shrink-0 -rotate-90">
      <circle cx="34" cy="34" r={r} fill="none" stroke="#EAE2D4" strokeWidth="7" />
      <circle
        cx="34" cy="34" r={r} fill="none"
        stroke={pct >= 100 ? "#15803D" : "#D97706"}
        strokeWidth="7"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - pct / 100)}
      />
      <text x="34" y="38" textAnchor="middle" className="rotate-90" transform="rotate(90 34 34)" fontSize="14" fontWeight="700" fill="#1C1917">
        {pct}%
      </text>
    </svg>
  );
}
