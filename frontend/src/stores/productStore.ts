"use client";

import { create } from "zustand";
import { api } from "@/lib/api";
import type { Product } from "@/types/api";

interface ProductState {
  byId: Record<string, Product>;
  loaded: boolean;
  loading: boolean;
  error: string | null;
  loadAll: () => Promise<void>;
  remember: (products: Product[]) => void;
}

export const useProductStore = create<ProductState>((set, get) => ({
  byId: {},
  loaded: false,
  loading: false,
  error: null,

  loadAll: async () => {
    if (get().loaded || get().loading) return;
    set({ loading: true, error: null });
    try {
      const res = await api.products({ page_size: 100 });
      const byId: Record<string, Product> = { ...get().byId };
      for (const p of res.items) byId[p.id] = p;
      set({ byId, loaded: true, loading: false });
    } catch (err) {
      set({ loading: false, error: err instanceof Error ? err.message : "Failed to load products" });
    }
  },

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
