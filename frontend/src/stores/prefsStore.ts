"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { EMPTY_PREFERENCES, type Preferences } from "@/types/api";

interface PrefsState {
  preferences: Preferences;
  quizSeen: boolean;
  setPreferences: (prefs: Preferences) => void;
  markQuizSeen: () => void;
}

export const usePrefsStore = create<PrefsState>()(
  persist(
    (set) => ({
      preferences: EMPTY_PREFERENCES,
      quizSeen: false,
      setPreferences: (preferences) => set({ preferences }),
      markQuizSeen: () => set({ quizSeen: true }),
    }),
    // v3: dropped the retired taxonomy/commerce preference fields (budget_tier, total_budget,
    // room_purpose, region, formality, luxury_tier, materials). The bump discards any stale v2
    // state so a returning client never posts a now-forbidden extra key to /assist/layout.
    // Rehydrated after mount (PlannerShell) so SSR and first client paint match.
    { name: "zory-prefs-v3", skipHydration: true },
  ),
);
