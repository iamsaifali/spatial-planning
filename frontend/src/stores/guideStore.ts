"use client";

import { create } from "zustand";
import type { AnalysisResponse } from "@/types/api";

/** Placement categories, kept as a stable ordering used by a few canvas affordances. */
export const STEP_ORDER = [
  "sofa",
  "tv_unit",
  "rug",
  "coffee_table",
  "side_table",
  "accent_chair",
  "lighting",
  "storage",
  "decor",
] as const;

export type StepKey = (typeof STEP_ORDER)[number];

/** Trimmed for the assist-only app: no step-by-step guide and no room-analysis endpoint.
 *  Retains the canvas-facing bits — the current selected category and the (off-by-default)
 *  analysis-overlay toggle. `analysis` stays null since /rooms/analyze was removed. */
interface GuideState {
  currentStepKey: StepKey;
  analysis: AnalysisResponse | null;
  overlaysVisible: boolean;
  setCurrentStep: (key: StepKey) => void;
  toggleOverlays: () => void;
}

export const useGuideStore = create<GuideState>((set) => ({
  currentStepKey: "sofa",
  analysis: null,
  overlaysVisible: false,

  setCurrentStep: (key) => set({ currentStepKey: key }),
  toggleOverlays: () => set((s) => ({ overlaysVisible: !s.overlaysVisible })),
}));
