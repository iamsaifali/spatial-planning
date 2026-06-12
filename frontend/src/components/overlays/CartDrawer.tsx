"use client";

import { Minus, Plus, ShoppingCart, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProductImage } from "@/components/ui/ProductImage";
import { Sheet } from "@/components/ui/Sheet";
import { useMoney } from "@/lib/format";
import { cartTotal, useCartStore } from "@/stores/cartStore";
import { useUiStore } from "@/stores/uiStore";

export function CartDrawer() {
  const open = useUiStore((s) => s.cartOpen);
  const setSheet = useUiStore((s) => s.setSheet);
  const lines = useCartStore((s) => s.lines);
  const setQty = useCartStore((s) => s.setQty);
  const remove = useCartStore((s) => s.remove);

  const money = useMoney();
  const total = cartTotal(lines);
  const close = () => setSheet("cartOpen", false);

  return (
    <Sheet
      open={open}
      onClose={close}
      title={`Cart (${lines.length})`}
      footer={
        lines.length > 0 ? (
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-faint">Total</p>
              <p className="text-base font-bold">{money(total)}</p>
            </div>
            <Button
              size="lg"
              onClick={() => {
                close();
                setSheet("checkoutOpen", true);
              }}
            >
              Checkout
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="p-4">
        {lines.length === 0 ? (
          <EmptyState
            icon={ShoppingCart}
            title="Your cart is empty"
            body='Add products from the recommendations, or use "Add all to cart" when your room is ready.'
          />
        ) : (
          <ul className="space-y-3">
            {lines.map(({ product, qty }) => (
              <li key={product.id} className="flex gap-3 rounded-lg border border-line p-2.5">
                <ProductImage src={product.image_url} alt="" className="h-16 w-16 shrink-0 rounded-md" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-semibold">{product.name}</p>
                  <p className="text-[10px] text-ink-faint">
                    {product.brand} · {product.delivery_days}d delivery
                  </p>
                  <p className="mt-1 text-sm font-bold">{money(product.price * qty)}</p>
                  {!product.in_stock && <p className="text-[10px] font-semibold text-warn">Out of stock - remove to checkout</p>}
                </div>
                <div className="flex flex-col items-end justify-between">
                  <button
                    onClick={() => remove(product.id)}
                    aria-label={`Remove ${product.name}`}
                    className="rounded-full p-1.5 text-ink-faint hover:bg-surface-2 hover:text-danger"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  <div className="flex items-center gap-1 rounded-full border border-line">
                    <button
                      onClick={() => setQty(product.id, qty - 1)}
                      aria-label="Decrease quantity"
                      className="flex h-7 w-7 items-center justify-center rounded-full text-ink-soft hover:bg-surface-2"
                    >
                      <Minus className="h-3 w-3" />
                    </button>
                    <span className="w-5 text-center text-xs font-bold">{qty}</span>
                    <button
                      onClick={() => setQty(product.id, qty + 1)}
                      aria-label="Increase quantity"
                      className="flex h-7 w-7 items-center justify-center rounded-full text-ink-soft hover:bg-surface-2"
                    >
                      <Plus className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Sheet>
  );
}
