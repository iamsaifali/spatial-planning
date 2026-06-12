"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { CurrencyConfig } from "@/types/api";

/** Fallbacks mirror the backend defaults; /config overwrites them at runtime. */
const FALLBACK: CurrencyConfig = {
  supported: ["USD", "SAR"],
  base: "USD",
  default: "SAR",
  rates: { USD: 1.0, SAR: 3.75 },
};

interface CurrencyState {
  currency: string; // selected display currency
  config: CurrencyConfig;
  hydrated: boolean;
  setCurrency: (code: string) => void;
  applyConfig: (config: CurrencyConfig) => void;
}

export const useCurrencyStore = create<CurrencyState>()(
  persist(
    (set, get) => ({
      currency: FALLBACK.default,
      config: FALLBACK,
      hydrated: false,

      setCurrency: (code) => {
        if (get().config.supported.includes(code)) set({ currency: code });
      },

      applyConfig: (config) =>
        set((s) => ({
          config,
          hydrated: true,
          // keep the user's choice when still valid, else fall back to server default
          currency: config.supported.includes(s.currency) ? s.currency : config.default,
        })),
    }),
    { name: "zory-currency-v1", partialize: (s) => ({ currency: s.currency }) },
  ),
);

export function rateFor(code: string): number {
  return useCurrencyStore.getState().config.rates[code] ?? 1.0;
}
