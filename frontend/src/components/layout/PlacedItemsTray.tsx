"use client";

import { ProductImage } from "@/components/ui/ProductImage";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";

/** Mockup parity: "N items in your room" + clickable thumbnails (md+). */
export function PlacedItemsTray() {
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);
  const select = useUiStore((s) => s.select);
  const selectedId = useUiStore((s) => s.selectedId);
  const issues = useUiStore((s) => s.itemIssues);

  if (items.length === 0) return null;

  return (
    <div className="hidden min-w-0 items-center gap-2 lg:flex">
      <p className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
        {items.length} item{items.length !== 1 ? "s" : ""} in your room
      </p>
      <div className="panel-scroll flex max-w-72 gap-1.5 overflow-x-auto xl:max-w-96 3xl:max-w-xl">
        {items.map((item) => {
          const product = byId[item.product_id];
          const name = item.custom?.name ?? product?.name ?? item.product_id;
          const selected = selectedId === item.instance_id;
          const issue = issues[item.instance_id];
          return (
            <button
              key={item.instance_id}
              onClick={() => select(selected ? null : item.instance_id)}
              title={name}
              aria-label={`Select ${name} on the canvas`}
              aria-pressed={selected}
              className={`relative h-9 w-9 shrink-0 overflow-hidden rounded-md border transition-colors ${
                selected ? "border-amber-deep" : "border-line hover:border-ink-faint"
              }`}
            >
              {product && product.image_url ? (
                <ProductImage src={product.image_url} alt="" className="h-full w-full" />
              ) : (
                <span className="flex h-full w-full items-center justify-center bg-beige-50 text-[9px] font-bold text-ink-soft">
                  {name.slice(0, 2).toUpperCase()}
                </span>
              )}
              {issue && (
                <span
                  className={`absolute top-0.5 right-0.5 h-2 w-2 rounded-full ${
                    issue === "error" ? "bg-danger" : "bg-warn"
                  }`}
                  aria-label="Placement needs attention"
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
