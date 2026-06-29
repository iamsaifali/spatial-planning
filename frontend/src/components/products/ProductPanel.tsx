"use client";

import { ArrowRight, Heart, PackageSearch, RotateCcw, SearchX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
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
};

export function ProductPanelContent() {
  const [tab, setTab] = useState<"recommended" | "all">("recommended");
  const currentStepKey = useGuideStore((s) => s.currentStepKey);
  const stepCache = useGuideStore((s) => s.stepCache);
  const stepLoading = useGuideStore((s) => s.stepLoading);
  const fetchStep = useGuideStore((s) => s.fetchStep);

  const step = stepCache[currentStepKey]?.data;
  const recs = step?.recommendations ?? [];
  const emptySlots = step?.empty_slots ?? [];
  const hero = recs.find((r) => r.slot === "best_match") ?? recs[0];
  const others = recs.filter((r) => r !== hero);

  return (
    <div className="flex h-full flex-col">
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
              {recs.length === 3
                ? `Three options that fit your ${CATEGORY_LABELS[currentStepKey].toLowerCase()} zone:`
                : `${recs.length} option${recs.length > 1 ? "s" : ""} fit this spot:`}
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
            <RecommendationCard key={rec.slot} rec={rec} />
          ))}
          {step && recs.length === 0 && (
            <EmptyState
              icon={SearchX}
              title="No good fit found"
              body={
                NO_FIT_HINTS[String(emptySlots[0]?.reason ?? "NO_FIT")] +
                (emptySlots[0]?.hints?.smallest_in_category_cm
                  ? ` Smallest option is ${emptySlots[0].hints.smallest_in_category_cm} cm; the zone is ${emptySlots[0].hints.zone_cm} cm.`
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
          {step && emptySlots.length > 0 && recs.length > 0 && (
            <p className="rounded-md bg-surface-2 p-2.5 text-[11px] leading-4 text-ink-soft">
              {emptySlots.length} slot{emptySlots.length > 1 ? "s" : ""} skipped:{" "}
              {NO_FIT_HINTS[String(emptySlots[0]?.reason ?? "NO_FIT")]}
            </p>
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

const BROWSE_PAGE_SIZE = 48;

function AllProductsTab() {
  const remember = useProductStore((s) => s.remember);
  const currentStepKey = useGuideStore((s) => s.currentStepKey);
  const favoriteIds = useFavoritesStore((s) => s.ids);

  const [category, setCategory] = useState<Category | "all">(currentStepKey);
  const [style, setStyle] = useState<string | "all">("all");
  const [maxPrice, setMaxPrice] = useState<number | null>(null);
  const [onlyFavorites, setOnlyFavorites] = useState(false);

  // the FULL category is fetched from the API, paginated ("Load more") - not the small
  // in-memory recommendation set, so every product in the catalog is browsable. We tag
  // the result with its query key and DERIVE `loading` (no setState in the effect body).
  const [data, setData] = useState<{ key: string; items: Product[]; total: number; page: number } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  // follow the guided step's category as it changes (adjust during render)
  const [prevStep, setPrevStep] = useState(currentStepKey);
  if (prevStep !== currentStepKey) {
    setPrevStep(currentStepKey);
    setCategory(currentStepKey);
  }

  const queryParams = useMemo(
    () => ({
      ...(category !== "all" ? { category } : {}),
      ...(style !== "all" ? { style } : {}),
      ...(maxPrice ? { max_price: maxPrice } : {}),
      sort: "relevance",
      page_size: BROWSE_PAGE_SIZE,
    }),
    [category, style, maxPrice],
  );
  const queryKey = JSON.stringify(queryParams);

  useEffect(() => {
    let alive = true;
    const key = JSON.stringify(queryParams);
    api
      .products({ ...queryParams, page: 1 })
      .then((res) => {
        if (!alive) return;
        remember(res.items);
        setData({ key, items: res.items, total: res.total, page: 1 });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [queryParams, remember]);

  const fresh = data && data.key === queryKey ? data : null; // null while (re)fetching
  const loading = !fresh;
  const items = fresh ? fresh.items : [];
  const total = fresh ? fresh.total : 0;

  const loadMore = async () => {
    if (!fresh) return;
    setLoadingMore(true);
    try {
      const next = fresh.page + 1;
      const res = await api.products({ ...queryParams, page: next });
      remember(res.items);
      setData({ key: queryKey, items: [...fresh.items, ...res.items], total: res.total, page: next });
    } finally {
      setLoadingMore(false);
    }
  };

  const products = onlyFavorites ? items.filter((p) => favoriteIds.includes(p.id)) : items;

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
        {loading ? (
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
          <>
            <p className="mb-2 px-0.5 text-[11px] text-ink-faint">
              {onlyFavorites
                ? `${products.length} favourite${products.length === 1 ? "" : "s"}`
                : `Showing ${items.length} of ${total}`}
            </p>
            <div className="grid grid-cols-2 gap-2">
              {products.map((product) => (
                <ProductCardSmall key={product.id} product={product} />
              ))}
            </div>
            {!onlyFavorites && items.length < total && (
              <div className="mt-3 flex justify-center">
                <Button variant="secondary" size="sm" loading={loadingMore} onClick={loadMore}>
                  Load more ({total - items.length} more)
                </Button>
              </div>
            )}
          </>
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
