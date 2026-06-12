"use client";

import { Heart, Plus, ShoppingCart, Star } from "lucide-react";
import { useState } from "react";
import { ProductImage } from "@/components/ui/ProductImage";
import { formatDims, useMoney } from "@/lib/format";
import { addProductToRoom } from "@/lib/placement";
import { useCartStore } from "@/stores/cartStore";
import { useFavoritesStore } from "@/stores/favoritesStore";
import { useUiStore } from "@/stores/uiStore";
import type { Product } from "@/types/api";

export function ProductCardSmall({ product }: { product: Product }) {
  const money = useMoney();
  const [busy, setBusy] = useState(false);
  const addToCart = useCartStore((s) => s.add);
  const toast = useUiStore((s) => s.toast);
  const isFavorite = useFavoritesStore((s) => s.ids.includes(product.id));
  const toggleFavorite = useFavoritesStore((s) => s.toggle);
  const hasMrp = product.mrp != null && product.mrp > product.price;

  const place = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const id = await addProductToRoom(product, { advance: false });
      if (id) toast("success", `${product.name} placed - drag to adjust.`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="group overflow-hidden rounded-lg border border-line bg-surface transition-[box-shadow,transform,border-color] duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:shadow-pop">
      <div className="relative">
        <ProductImage src={product.image_url} alt={product.name} className="h-24 w-full" />
        {!product.in_stock && (
          <span className="absolute top-1.5 left-1.5 rounded-full bg-surface px-2 py-0.5 text-[10px] font-semibold text-ink-soft">
            Out of stock
          </span>
        )}
        <button
          onClick={() => toggleFavorite(product.id)}
          aria-label={isFavorite ? `Remove ${product.name} from favourites` : `Save ${product.name} to favourites`}
          aria-pressed={isFavorite}
          className="absolute top-1.5 right-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-surface/90 shadow-soft"
        >
          <Heart className={`h-3.5 w-3.5 ${isFavorite ? "fill-amber-deep text-amber-deep" : "text-ink-soft"}`} aria-hidden />
        </button>
      </div>
      <div className="space-y-1 p-2">
        <h4 className="truncate text-xs font-semibold" title={product.name}>
          {product.name}
        </h4>
        <p className="text-[10px] text-ink-faint">{formatDims(product.width_cm, product.depth_cm)}</p>
        <div className="flex items-center justify-between">
          <p className="text-xs font-bold">
            {money(product.price)}
            {hasMrp && (
              <span className="ml-1 text-[9px] font-medium text-ink-faint line-through">
                {money(product.mrp!)}
              </span>
            )}
          </p>
          <span className="inline-flex items-center gap-0.5 text-[10px] text-ink-soft">
            <Star className="h-2.5 w-2.5 fill-amber text-amber" aria-hidden />
            {product.rating}
          </span>
        </div>
        <div className="flex gap-1 pt-0.5">
          <button
            onClick={() => void place()}
            disabled={busy}
            className="flex h-7 flex-1 items-center justify-center gap-1 rounded-full bg-accent text-[10px] font-semibold text-accent-ink disabled:opacity-50"
            title="Place on canvas"
          >
            <Plus className="h-3 w-3" /> Place
          </button>
          <button
            onClick={() => {
              addToCart(product);
              toast("success", `${product.name} added to cart.`);
            }}
            className="flex h-7 w-8 items-center justify-center rounded-full border border-line text-ink-soft hover:bg-surface-2"
            title="Add to cart"
            aria-label={`Add ${product.name} to cart`}
          >
            <ShoppingCart className="h-3 w-3" />
          </button>
        </div>
      </div>
    </article>
  );
}
