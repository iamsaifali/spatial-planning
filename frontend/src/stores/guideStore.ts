"use client";

import { create } from "zustand";
import { api, ApiError, NetworkError } from "@/lib/api";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useProductStore } from "@/stores/productStore";
import type { AnalysisResponse, StepInfo, StepResponse } from "@/types/api";

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

interface CachedStep {
  data: StepResponse;
  roomVersion: number;
  itemsSignature: string;
}

interface GuideState {
  steps: StepInfo[];
  currentStepKey: StepKey;
  skipped: Set<string>;
  stepCache: Record<string, CachedStep>;
  stepLoading: boolean;
  stepError: string | null;
  analysis: AnalysisResponse | null;
  analysisLoading: boolean;
  analysisError: string | null;
  overlaysVisible: boolean;
  guideFinished: boolean;

  setCurrentStep: (key: StepKey) => void;
  skipStep: (key: StepKey) => void;
  advanceAfterPlacement: () => void;
  fetchStep: (key?: StepKey, force?: boolean) => Promise<StepResponse | null>;
  fetchAnalysis: () => Promise<void>;
  invalidateAll: () => void;
  toggleOverlays: () => void;
  setGuideFinished: (v: boolean) => void;
}

function itemsSignature(): string {
  return usePlannerStore
    .getState()
    .items.map((i) => `${i.instance_id}:${i.product_id}:${i.x.toFixed(0)},${i.y.toFixed(0)},${i.rotation_deg}`)
    .sort()
    .join("|");
}

export const useGuideStore = create<GuideState>((set, get) => ({
  steps: [],
  currentStepKey: "sofa",
  skipped: new Set(),
  stepCache: {},
  stepLoading: false,
  stepError: null,
  analysis: null,
  analysisLoading: false,
  analysisError: null,
  overlaysVisible: false,
  guideFinished: false,

  setCurrentStep: (key) => {
    set({ currentStepKey: key, guideFinished: false });
    void get().fetchStep(key);
  },

  skipStep: (key) => {
    const skipped = new Set(get().skipped);
    skipped.add(key);
    set({ skipped });
    get().advanceAfterPlacement();
  },

  advanceAfterPlacement: () => {
    const placedCategories = new Set(
      usePlannerStore.getState().items.map((i) => {
        const product = useProductStore.getState().byId[i.product_id];
        return product?.category ?? "";
      }),
    );
    const { skipped, currentStepKey } = get();
    const start = STEP_ORDER.indexOf(currentStepKey);
    for (let offset = 1; offset <= STEP_ORDER.length; offset++) {
      const key = STEP_ORDER[(start + offset) % STEP_ORDER.length];
      if (!placedCategories.has(key) && !skipped.has(key)) {
        set({ currentStepKey: key });
        void get().fetchStep(key);
        return;
      }
    }
    set({ guideFinished: true });
  },

  fetchStep: async (key, force = false) => {
    const stepKey = key ?? get().currentStepKey;
    const { room, roomVersion, items } = usePlannerStore.getState();
    const signature = itemsSignature();
    const cached = get().stepCache[stepKey];
    if (
      !force &&
      cached &&
      cached.roomVersion === roomVersion &&
      cached.itemsSignature === signature
    ) {
      return cached.data;
    }
    set({ stepLoading: true, stepError: null });
    try {
      const prefs = usePrefsStore.getState().preferences;
      const data = await api.guideStep(stepKey, room, prefs, items);
      useProductStore.getState().remember(data.recommendations.map((r) => r.product));
      set((s) => ({
        stepLoading: false,
        stepCache: {
          ...s.stepCache,
          [stepKey]: { data, roomVersion, itemsSignature: signature },
        },
      }));
      return data;
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return null;
      const message =
        err instanceof ApiError || err instanceof NetworkError
          ? err.message
          : "Couldn't load this step.";
      set({ stepLoading: false, stepError: message });
      return null;
    }
  },

  fetchAnalysis: async () => {
    const { room } = usePlannerStore.getState();
    set({ analysisLoading: true, analysisError: null });
    try {
      const analysis = await api.analyzeRoom(room);
      set({ analysis, analysisLoading: false });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const message =
        err instanceof ApiError ? err.message : "Couldn't analyze the room.";
      set({ analysisLoading: false, analysisError: message, analysis: null });
    }
  },

  invalidateAll: () => set({ stepCache: {}, analysis: null }),

  toggleOverlays: () => set((s) => ({ overlaysVisible: !s.overlaysVisible })),

  setGuideFinished: (v) => set({ guideFinished: v }),
}));

export function currentStepData(): StepResponse | null {
  const s = useGuideStore.getState();
  return s.stepCache[s.currentStepKey]?.data ?? null;
}
