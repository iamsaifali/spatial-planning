"use client";

import { ChevronDown, Heart, Plus, Star, Truck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { ProductImage } from "@/components/ui/ProductImage";
import { STYLE_LABELS } from "@/lib/constants";
import { formatDimsLabelled, useMoney } from "@/lib/format";
import { addProductToRoom, swapProduct } from "@/lib/placement";
import { useFavoritesStore } from "@/stores/favoritesStore";
import { useGuideStore } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import type { Recommendation } from "@/types/api";

const NOTICE_LABELS: Record<string, string> = {
  PREORDER: "Pre-order",
  TIGHT_FIT: "Tight fit",
};

export function RecommendationCard({
  rec,
  hero = false,
}: {
  rec: Recommendation;
  hero?: boolean;
}) {
  const money = useMoney();
  const [why, setWhy] = useState(false);
  const [busy, setBusy] = useState(false);
  const product = rec.product;

  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);
  const isFavorite = useFavoritesStore((s) => s.ids.includes(product.id));
  const toggleFavorite = useFavoritesStore((s) => s.toggle);
  const planSteps = useGuideStore((s) => s.planSteps);
  const placedSameCategory = items.find((i) => byId[i.product_id]?.category === product.category);
  const placedInCategory = items.filter((i) => byId[i.product_id]?.category === product.category).length;
  const alreadyPlaced = items.some((i) => i.product_id === product.id);
  // how many of this category the plan wants (defaults to 1 for un-planned categories)
  const plannedQty = planSteps.find((s) => s.category === product.category)?.quantity ?? 1;
  const atCapacity = placedInCategory >= plannedQty;
  const hasMrp = product.mrp != null && product.mrp > product.price;

  const onAdd = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (!atCapacity) {
        // category under its planned quantity -> add another. The first uses the
        // recommended spot; extra instances re-suggest (no pose) so the backend
        // spreads them (e.g. the 2nd side table flanks the other side of the sofa).
        await addProductToRoom(
          product,
          placedInCategory === 0 ? { pose: rec.suggested_pose, zoneId: rec.zone_id } : {},
        );
        useUiStore.getState().toast("success", `${product.name} placed on your canvas.`);
      } else if (placedSameCategory && !alreadyPlaced) {
        // category is full -> swap replaces an existing piece rather than exceeding the plan
        await swapProduct(placedSameCategory.instance_id, product);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <article
      className={`overflow-hidden rounded-lg border bg-surface transition-[box-shadow,transform,border-color] duration-200 hover:-translate-y-0.5 hover:shadow-pop ${
        hero ? "border-amber/40 shadow-soft" : "border-line hover:border-line-strong"
      }`}
    >
      <div className="relative">
        <ProductImage src={product.image_url} alt={product.name} className={`w-full ${hero ? "h-40" : "h-24"}`} />
        <div className="absolute top-2 left-2 flex flex-wrap gap-1">
          {rec.rank === 0 ? <Chip tone="amber">Best match</Chip> : null}
          {rec.notices.map((n) =>
            NOTICE_LABELS[n] ? (
              <Chip key={n} tone="warn">
                {NOTICE_LABELS[n]}
              </Chip>
            ) : null,
          )}
        </div>
        {!product.in_stock && (
          <div className="absolute right-2 bottom-2">
            <Chip tone="neutral">Out of stock</Chip>
          </div>
        )}
        <button
          onClick={() => toggleFavorite(product.id)}
          aria-label={isFavorite ? `Remove ${product.name} from favourites` : `Save ${product.name} to favourites`}
          aria-pressed={isFavorite}
          className="absolute top-2 right-2 flex h-8 w-8 items-center justify-center rounded-full bg-surface/90 shadow-soft"
        >
          <Heart
            className={`h-4 w-4 ${isFavorite ? "fill-amber-deep text-amber-deep" : "text-ink-soft"}`}
            aria-hidden
          />
        </button>
      </div>

      <div className={`space-y-2 ${hero ? "p-3.5" : "p-2.5"}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className={`truncate font-semibold ${hero ? "text-sm" : "text-[13px]"}`}>{product.name}</h3>
            <p className="text-[11px] text-ink-faint">
              {product.brand} · {formatDimsLabelled(product.width_cm, product.depth_cm, product.height_cm)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className={`font-bold ${hero ? "text-sm" : "text-[13px]"}`}>{money(product.price)}</p>
            {hasMrp && (
              <p className="text-[10px] text-ink-faint line-through">{money(product.mrp!)}</p>
            )}
          </div>
        </div>

        {hero && (
          <div className="flex flex-wrap gap-1">
            {product.style_tags.slice(0, 1).map((tag) => (
              <Chip key={tag} tone="neutral">{STYLE_LABELS[tag] ?? tag}</Chip>
            ))}
            {product.colors.slice(0, 1).map((color) => (
              <Chip key={color} tone="neutral">{color}</Chip>
            ))}
            {product.materials.slice(0, 1).map((material) => (
              <Chip key={material} tone="neutral">{material}</Chip>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2 text-[11px] text-ink-soft">
          <span className="inline-flex items-center gap-0.5">
            <Star className="h-3 w-3 fill-amber text-amber" aria-hidden /> {product.rating}
          </span>
          <span className="inline-flex items-center gap-1">
            <Truck className="h-3 w-3" aria-hidden /> {product.delivery_days}d delivery
          </span>
        </div>

        <button
          onClick={() => setWhy((v) => !v)}
          className="flex w-full items-center justify-between text-left text-[11px] font-semibold text-amber-deep"
          aria-expanded={why}
        >
          Why this {hero ? "pick" : "one"}?
          <ChevronDown className={`h-3.5 w-3.5 transition-transform ${why ? "rotate-180" : ""}`} />
        </button>
        {why && (
          <ul className="space-y-1.5 rounded-md bg-surface-2 p-2.5 text-[11px] leading-4 text-ink-soft">
            <li>{rec.why_it_fits.why_product}</li>
            <li>{rec.why_it_fits.why_size}</li>
            <li>{rec.why_it_fits.why_placement}</li>
          </ul>
        )}

        <Button
          onClick={() => void onAdd()}
          loading={busy}
          disabled={atCapacity && alreadyPlaced}
          size={hero ? "md" : "sm"}
          className="w-full"
          variant={hero ? "primary" : "secondary"}
        >
          {!busy && <Plus className="h-3.5 w-3.5" />}
          {!atCapacity ? "Add to room" : alreadyPlaced ? "In your room" : "Swap into room"}
        </Button>
      </div>
    </article>
  );
}
