"use client";

import { ArrowRight, Heart, PackageSearch, RotateCcw, SearchX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { EmptyState } from "@/components/ui/EmptyState";
import { RecommendationSkeleton } from "@/components/ui/Skeleton";
import { CATEGORY_LABELS, CATEGORY_PLURALS, STYLE_LABELS } from "@/lib/constants";
import { useMoney } from "@/lib/format";
import { useFavoritesStore } from "@/stores/favoritesStore";
import { useGuideStore } from "@/stores/guideStore";
import { useProductStore } from "@/stores/productStore";
import type { Category, Product } from "@/types/api";
import { ProductCardSmall } from "./ProductCardSmall";
import { RecommendationCard } from "./RecommendationCard";

const NO_FIT_HINTS: Record<string, string> = {
  NO_FIT: "Nothing in this category fits the available space.",
  no_zones: "There's no clear spot for this category in the current layout.",
  empty_category: "No products available in this category yet.",
  SKIPPED_TIGHT_SPACE:
    "Left out to keep the room comfortable — there's no clear spot for it without crowding a walkway. It's optional, so the layout skips it.",
};

export function ProductPanelContent() {
  const [tab, setTab] = useState<"recommended" | "all">("recommended");
  const currentStepKey = useGuideStore((s) => s.currentStepKey);
  const stepCache = useGuideStore((s) => s.stepCache);
  const stepLoading = useGuideStore((s) => s.stepLoading);
  const fetchStep = useGuideStore((s) => s.fetchStep);

  const seatingNote = useGuideStore((s) => s.seatingNote);

  const step = stepCache[currentStepKey]?.data;
  const recs = step?.recommendations ?? [];
  const noFit = step?.no_fit ?? null;
  const hero = recs[0];
  const others = recs.slice(1);

  return (
    <div className="flex h-full flex-col">
      {seatingNote && (
        <div className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
          {seatingNote}
        </div>
      )}
      <div className="flex gap-1 border-b border-line p-2">
        {(["recommended", "all"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            aria-pressed={tab === t}
            className={`flex-1 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${
              tab === t ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-surface-2"
            }`}
          >
            {t === "recommended" ? "Recommended" : `All ${CATEGORY_PLURALS[currentStepKey]}`}
          </button>
        ))}
      </div>

      {tab === "recommended" ? (
        <div className="panel-scroll flex-1 space-y-3 overflow-y-auto p-3">
          {step && recs.length > 0 && (
            <p className="text-xs leading-5 text-ink-soft">
              {`${recs.length} ${CATEGORY_LABELS[currentStepKey].toLowerCase()} option${recs.length > 1 ? "s" : ""} that fit your space — best match first:`}
            </p>
          )}
          {step && step.quantity > 1 && (
            <p className="rounded-md bg-amber-faint p-2 text-[11px] leading-4 text-amber-deep">
              ZORY suggests {step.quantity} of these for this room — add them one at a time and they&apos;ll be spaced out.
            </p>
          )}
          {stepLoading && !step && (
            <>
              <RecommendationSkeleton />
              <RecommendationSkeleton />
            </>
          )}
          {hero && <RecommendationCard rec={hero} hero />}
          {others.map((rec) => (
            <RecommendationCard key={rec.product.id} rec={rec} />
          ))}
          {step && recs.length === 0 && (
            <EmptyState
              icon={SearchX}
              title="No good fit found"
              body={
                NO_FIT_HINTS[String(noFit?.reason ?? "NO_FIT")] +
                (noFit?.hints?.smallest_in_category_cm
                  ? ` Smallest option is ${noFit.hints.smallest_in_category_cm} cm; the zone is ${noFit.hints.zone_cm} cm.`
                  : "")
              }
              action={
                <Button size="sm" variant="secondary" onClick={() => void fetchStep(undefined, true)}>
                  <RotateCcw className="h-3.5 w-3.5" /> Re-check
                </Button>
              }
            />
          )}
          {!step && !stepLoading && (
            <EmptyState
              icon={PackageSearch}
              title="Recommendations load here"
              body="Draw or adjust your room and ZORY will pick products that fit."
            />
          )}
          {step && (
            <button
              onClick={() => setTab("all")}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-line bg-surface px-3 py-2 text-xs font-semibold text-ink-soft hover:border-ink-faint hover:text-ink"
            >
              See all {CATEGORY_LABELS[currentStepKey].toLowerCase()}s
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </div>
      ) : (
        <AllProductsTab />
      )}
    </div>
  );
}

function AllProductsTab() {
  const byId = useProductStore((s) => s.byId);
  const loaded = useProductStore((s) => s.loaded);
  const loadAll = useProductStore((s) => s.loadAll);
  const currentStepKey = useGuideStore((s) => s.currentStepKey);
  const favoriteIds = useFavoritesStore((s) => s.ids);

  const [category, setCategory] = useState<Category | "all">(currentStepKey);
  const [style, setStyle] = useState<string | "all">("all");
  const [maxPrice, setMaxPrice] = useState<number | null>(null);
  const [onlyFavorites, setOnlyFavorites] = useState(false);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // follow the guided step's category as it changes (adjust during render)
  const [prevStep, setPrevStep] = useState(currentStepKey);
  if (prevStep !== currentStepKey) {
    setPrevStep(currentStepKey);
    setCategory(currentStepKey);
  }

  const products = useMemo(() => {
    let list = Object.values(byId).filter((p) => p.category !== "custom");
    if (onlyFavorites) list = list.filter((p) => favoriteIds.includes(p.id));
    if (category !== "all") list = list.filter((p) => p.category === category);
    if (style !== "all") list = list.filter((p) => p.style_tags.includes(style as Product["style_tags"][number]));
    if (maxPrice) list = list.filter((p) => p.price <= maxPrice);
    return list.sort((a, b) => b.rating - a.rating || a.price - b.price);
  }, [byId, category, style, maxPrice, onlyFavorites, favoriteIds]);

  const money = useMoney();
  const priceCaps = [100, 300, 600, 1200]; // base-currency (USD) steps
  const shoppableCategories = (Object.keys(CATEGORY_LABELS) as Category[]).filter((c) => c !== "custom");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2 border-b border-line p-2.5">
        <div className="panel-scroll flex gap-1 overflow-x-auto pb-1">
          <FilterChip active={category === "all"} onClick={() => setCategory("all")} label="All" />
          {shoppableCategories.map((c) => (
            <FilterChip key={c} active={category === c} onClick={() => setCategory(c)} label={CATEGORY_LABELS[c]} />
          ))}
          <button
            onClick={() => setOnlyFavorites((v) => !v)}
            aria-pressed={onlyFavorites}
            className={`flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap transition-colors ${
              onlyFavorites
                ? "border-amber-deep bg-amber-soft text-amber-deep"
                : "border-line bg-surface text-ink-soft hover:border-ink-faint"
            }`}
          >
            <Heart className={`h-3 w-3 ${onlyFavorites ? "fill-amber-deep" : ""}`} aria-hidden />
            Favourites{favoriteIds.length > 0 ? ` (${favoriteIds.length})` : ""}
          </button>
        </div>
        <div className="panel-scroll flex gap-1 overflow-x-auto pb-1">
          <FilterChip active={style === "all"} onClick={() => setStyle("all")} label="Any style" />
          {Object.entries(STYLE_LABELS).map(([key, label]) => (
            <FilterChip key={key} active={style === key} onClick={() => setStyle(key)} label={label} />
          ))}
        </div>
        <div className="panel-scroll flex gap-1 overflow-x-auto pb-1">
          <FilterChip active={maxPrice === null} onClick={() => setMaxPrice(null)} label="Any price" />
          {priceCaps.map((cap) => (
            <FilterChip
              key={cap}
              active={maxPrice === cap}
              onClick={() => setMaxPrice(cap)}
              label={`≤ ${money(cap)}`}
            />
          ))}
        </div>
      </div>

      <div className="panel-scroll flex-1 overflow-y-auto p-2.5">
        {!loaded ? (
          <div className="grid grid-cols-2 gap-2">
            <RecommendationSkeleton />
            <RecommendationSkeleton />
          </div>
        ) : products.length === 0 ? (
          <EmptyState
            icon={SearchX}
            title="Nothing matches"
            body="Try loosening the filters."
            action={
              <Chip tone="amber" className="cursor-pointer" >
                <button onClick={() => { setStyle("all"); setMaxPrice(null); }}>Reset filters</button>
              </Chip>
            }
          />
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {products.map((product) => (
              <ProductCardSmall key={product.id} product={product} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FilterChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap transition-colors ${
        active
          ? "border-accent bg-accent text-accent-ink"
          : "border-line bg-surface text-ink-soft hover:border-ink-faint"
      }`}
    >
      {label}
    </button>
  );
}

/** Desktop right column. */
export function ProductPanel() {
  return (
    <aside
      className="hidden h-full min-h-0 flex-col border-l border-line bg-surface lg:flex"
      aria-label="Product recommendations"
    >
      <ProductPanelContent />
    </aside>
  );
}
