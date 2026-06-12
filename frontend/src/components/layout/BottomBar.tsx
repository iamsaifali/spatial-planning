"use client";

import { Camera, Info, Move3d, ShoppingCart } from "lucide-react";
import { useMemo } from "react";
import { Button } from "@/components/ui/Button";
import { savingsOf, useMoney } from "@/lib/format";
import { useCartStore } from "@/stores/cartStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import { PlacedItemsTray } from "./PlacedItemsTray";

export function useRoomTotal(): { total: number; count: number; save: number; savePct: number } {
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);
  return useMemo(() => {
    const products = items.map((i) => byId[i.product_id]).filter(Boolean);
    const total = products.reduce((sum, p) => sum + p.price, 0);
    const { save, pct } = savingsOf(products);
    return { total, count: products.length, save, savePct: pct };
  }, [items, byId]);
}

export function addAllToCart(): number {
  const items = usePlannerStore.getState().items;
  const byId = useProductStore.getState().byId;
  const products = items.map((i) => byId[i.product_id]).filter(Boolean);
  if (products.length === 0) return 0;
  useCartStore.getState().addMany(products);
  return products.length;
}

/** Desktop/tablet bottom bar (hidden on phones, where MobileStepBar takes over). */
export function BottomBar() {
  const { total, count, save, savePct } = useRoomTotal();
  const money = useMoney();
  const setSheet = useUiStore((s) => s.setSheet);
  const toast = useUiStore((s) => s.toast);

  return (
    <footer className="hidden h-14 shrink-0 items-center gap-3 border-t border-line bg-surface px-4 md:flex">
      <PlacedItemsTray />
      <div className="min-w-0 lg:ml-2">
        <p
          className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap text-ink-faint"
          title="Sum of the products placed in your room, at current prices."
        >
          Estimated total
          <Info className="h-3 w-3" aria-hidden />
        </p>
        <p className="text-sm font-bold leading-4 whitespace-nowrap">
          {money(total)}
          <span className="ml-1.5 text-[11px] font-medium text-ink-faint">
            {count} item{count !== 1 ? "s" : ""}
          </span>
          {save > 0 && (
            <span className="ml-1.5 hidden text-[11px] font-semibold text-success lg:inline">
              You save {money(save)} ({savePct}%)
            </span>
          )}
        </p>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <Button variant="secondary" size="md" onClick={() => setSheet("view3DOpen", true)} className="whitespace-nowrap">
          <Move3d className="h-4 w-4" />
          <span className="hidden lg:inline">View room in 3D</span>
          <span className="lg:hidden">3D view</span>
        </Button>
        <Button variant="secondary" size="md" onClick={() => setSheet("renderOpen", true)} className="whitespace-nowrap">
          <Camera className="h-4 w-4" />
          <span className="hidden lg:inline">AI photo preview</span>
          <span className="lg:hidden">AI preview</span>
        </Button>
        <Button
          size="md"
          className="whitespace-nowrap"
          onClick={() => {
            const added = addAllToCart();
            if (added === 0) toast("info", "Place some products first.");
            else {
              toast("success", `${added} item${added > 1 ? "s" : ""} added to cart.`);
              setSheet("cartOpen", true);
            }
          }}
        >
          <ShoppingCart className="h-4 w-4" />
          Add all to cart
        </Button>
      </div>
    </footer>
  );
}
