"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Product } from "@/types/api";

export interface CartLine {
  product: Product; // snapshot so the cart survives reloads offline
  qty: number;
}

interface CartState {
  lines: CartLine[];
  add: (product: Product, qty?: number) => void;
  addMany: (products: Product[]) => void;
  remove: (productId: string) => void;
  setQty: (productId: string, qty: number) => void;
  clear: () => void;
}

export const useCartStore = create<CartState>()(
  persist(
    (set) => ({
      lines: [],

      add: (product, qty = 1) =>
        set((s) => {
          const existing = s.lines.find((l) => l.product.id === product.id);
          if (existing) {
            return {
              lines: s.lines.map((l) =>
                l.product.id === product.id ? { ...l, qty: Math.min(20, l.qty + qty) } : l,
              ),
            };
          }
          return { lines: [...s.lines, { product, qty }] };
        }),

      addMany: (products) =>
        set((s) => {
          const lines = [...s.lines];
          for (const product of products) {
            const existing = lines.find((l) => l.product.id === product.id);
            if (existing) existing.qty = Math.min(20, existing.qty + 1);
            else lines.push({ product, qty: 1 });
          }
          return { lines };
        }),

      remove: (productId) =>
        set((s) => ({ lines: s.lines.filter((l) => l.product.id !== productId) })),

      setQty: (productId, qty) =>
        set((s) => ({
          lines:
            qty <= 0
              ? s.lines.filter((l) => l.product.id !== productId)
              : s.lines.map((l) => (l.product.id === productId ? { ...l, qty: Math.min(20, qty) } : l)),
        })),

      clear: () => set({ lines: [] }),
    }),
    // v2: product snapshots use currency-neutral price/mrp fields
    // rehydrated after mount (PlannerShell) so SSR and first client paint match
    { name: "zory-cart-v2", skipHydration: true },
  ),
);

export function cartTotal(lines: CartLine[]): number {
  return lines.reduce((sum, l) => sum + l.product.price * l.qty, 0);
}

export function cartCount(lines: CartLine[]): number {
  return lines.reduce((sum, l) => sum + l.qty, 0);
}
