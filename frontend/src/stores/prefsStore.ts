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
    // v2: preference fields are currency-neutral (total_budget in base currency)
    // rehydrated after mount (PlannerShell) so SSR and first client paint match
    { name: "zory-prefs-v2", skipHydration: true },
  ),
);
