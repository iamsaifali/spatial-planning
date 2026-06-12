"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface FavoritesState {
  ids: string[];
  toggle: (productId: string) => void;
  has: (productId: string) => boolean;
}

export const useFavoritesStore = create<FavoritesState>()(
  persist(
    (set, get) => ({
      ids: [],
      toggle: (productId) =>
        set((s) => ({
          ids: s.ids.includes(productId)
            ? s.ids.filter((id) => id !== productId)
            : [...s.ids, productId],
        })),
      has: (productId) => get().ids.includes(productId),
    }),
    { name: "zory-favorites-v1" },
  ),
);
