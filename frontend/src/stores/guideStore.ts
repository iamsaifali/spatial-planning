"use client";

import { create } from "zustand";
import { api, ApiError, NetworkError } from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/constants";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useProductStore } from "@/stores/productStore";
import type { AnalysisResponse, StepInfo, StepResponse } from "@/types/api";

// Canonical full ordering + the set of valid step keys. The LLM plan always
// chooses a SUBSET of these categories, so StepKey stays this union.
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

/** Steps shown before a plan loads (or if the plan call fails): the full set. */
const DEFAULT_PLAN_STEPS: StepInfo[] = STEP_ORDER.map((key, i) => ({
  key,
  category: key,
  title: CATEGORY_LABELS[key],
  order: i + 1,
  status: "pending",
  quantity: 1,
  placed_count: 0,
}));

interface CachedStep {
  data: StepResponse;
  roomVersion: number;
  itemsSignature: string;
}

interface GuideState {
  planSteps: StepInfo[];
  planSource: string | null;
  seatingNote: string | null;
  planLoading: boolean;
  currentStepKey: StepKey;
  skipped: Set<string>;
  // open-ended ("fill") steps the geometry has reported full, so we stop offering more and
  // advance past them - even though their soft quantity may not have been reached.
  filled: Set<string>;
  stepCache: Record<string, CachedStep>;
  stepLoading: boolean;
  stepError: string | null;
  analysis: AnalysisResponse | null;
  analysisLoading: boolean;
  analysisError: string | null;
  overlaysVisible: boolean;
  guideFinished: boolean;
  planningStarted: boolean;

  startPlanning: () => void;
  setCurrentStep: (key: StepKey) => void;
  skipStep: (key: StepKey) => void;
  advanceAfterPlacement: () => void;
  /** the geometry has no more room for `category` (a fill step or a tight room) - mark it
   *  satisfied and move on, instead of leaving the user stuck unable to place or advance. */
  completeFillStep: (category: string) => void;
  fetchPlan: () => Promise<void>;
  fetchStep: (key?: StepKey, force?: boolean) => Promise<StepResponse | null>;
  fetchAnalysis: () => Promise<void>;
  invalidateAll: () => void;
  reset: () => void;
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

/** Live count of placed items per furniture category. */
function placedCountsByCategory(): Record<string, number> {
  const byId = useProductStore.getState().byId;
  const counts: Record<string, number> = {};
  for (const it of usePlannerStore.getState().items) {
    const cat = byId[it.product_id]?.category;
    if (cat) counts[cat] = (counts[cat] ?? 0) + 1;
  }
  return counts;
}

export const useGuideStore = create<GuideState>((set, get) => ({
  planSteps: DEFAULT_PLAN_STEPS,
  planSource: null,
  seatingNote: null,
  planLoading: false,
  currentStepKey: "sofa",
  skipped: new Set(),
  filled: new Set(),
  stepCache: {},
  stepLoading: false,
  stepError: null,
  analysis: null,
  analysisLoading: false,
  analysisError: null,
  overlaysVisible: false,
  guideFinished: false,
  planningStarted: false,

  // run the analyze -> plan -> recommend pipeline; called once the user has a
  // room they're happy with (sample chosen, template applied, or drawn).
  startPlanning: () => {
    if (!get().planningStarted) set({ planningStarted: true });
    void get().fetchAnalysis();
    void get().fetchPlan();
    void get().fetchStep(undefined, true);
  },

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
    const counts = placedCountsByCategory();
    const { skipped, filled, currentStepKey } = get();
    const order = get().planSteps.length ? get().planSteps : DEFAULT_PLAN_STEPS;
    const startIdx = Math.max(0, order.findIndex((s) => s.key === currentStepKey));

    // a fill step (e.g. majlis sofas) keeps wanting more until the geometry reports it full
    // (completeFillStep adds it to `filled`); a normal step until its quantity is met.
    const wantsMore = (s: StepInfo) =>
      !skipped.has(s.key) &&
      !filled.has(s.key) &&
      (s.fill ? true : (counts[s.category] ?? 0) < s.quantity);

    // multi-instance: stay on the current category until it's satisfied
    const cur = order[startIdx];
    if (cur && wantsMore(cur)) {
      void get().fetchStep(cur.key as StepKey, true);
      return;
    }
    for (let offset = 1; offset <= order.length; offset++) {
      const step = order[(startIdx + offset) % order.length];
      if (wantsMore(step)) {
        set({ currentStepKey: step.key as StepKey });
        void get().fetchStep(step.key as StepKey);
        return;
      }
    }
    set({ guideFinished: true });
  },

  completeFillStep: (category) => {
    const step = (get().planSteps.length ? get().planSteps : DEFAULT_PLAN_STEPS).find(
      (s) => s.category === category,
    );
    const key = step?.key ?? category;
    const filled = new Set(get().filled);
    filled.add(key);
    set({ filled });
    get().advanceAfterPlacement();
  },

  fetchPlan: async () => {
    const { room, items } = usePlannerStore.getState();
    const prefs = usePrefsStore.getState().preferences;
    set({ planLoading: true });
    try {
      const res = await api.plan(room, prefs, items);
      const steps = res.steps.length ? res.steps : DEFAULT_PLAN_STEPS;
      set({
        planSteps: steps,
        planSource: res.plan_source,
        seatingNote: res.plan?.seating_note ?? null,
        planLoading: false,
      });
      // keep the current step valid; if the plan dropped it, jump to the first unfinished
      const keys = new Set(steps.map((s) => s.key));
      if (!keys.has(get().currentStepKey)) {
        const target = steps.find((s) => s.status === "current") ?? steps[0];
        if (target) {
          set({ currentStepKey: target.key as StepKey, guideFinished: false });
          void get().fetchStep(target.key as StepKey);
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      // the plan is advisory - keep whatever step list we already had
      set({ planLoading: false });
    }
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

  reset: () =>
    set({
      currentStepKey: "sofa",
      skipped: new Set(),
      filled: new Set(),
      stepCache: {},
      stepError: null,
      analysis: null,
      analysisError: null,
      guideFinished: false,
      planSteps: DEFAULT_PLAN_STEPS,
      planSource: null,
      seatingNote: null,
      planningStarted: false,
    }),

  toggleOverlays: () => set((s) => ({ overlaysVisible: !s.overlaysVisible })),

  setGuideFinished: (v) => set({ guideFinished: v }),
}));

export function currentStepData(): StepResponse | null {
  const s = useGuideStore.getState();
  return s.stepCache[s.currentStepKey]?.data ?? null;
}
