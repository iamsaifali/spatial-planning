"use client";

import { create } from "zustand";
import type { Product } from "@/types/api";

/** In-memory cache of products the assist layout has returned, keyed by id, so the
 *  canvas and 3D view can look up dimensions/images by product id. Populated via
 *  `remember()` from the assist response (there is no product-browsing endpoint). */
interface ProductState {
  byId: Record<string, Product>;
  remember: (products: Product[]) => void;
}

export const useProductStore = create<ProductState>((set) => ({
  byId: {},

  remember: (products) =>
    set((s) => {
      const byId = { ...s.byId };
      for (const p of products) byId[p.id] = p;
      return { byId };
    }),
}));

export function useProduct(productId: string | null | undefined): Product | undefined {
  return useProductStore((s) => (productId ? s.byId[productId] : undefined));
}
