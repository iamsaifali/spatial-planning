"use client";

import { create } from "zustand";
import type { Pose, ValidateResponse } from "@/types/api";

export type Tool = "select" | "wall" | "door" | "window" | "measure";

export interface Toast {
  id: number;
  kind: "info" | "success" | "error";
  message: string;
}

export interface ActiveWarning {
  instanceId: string;
  result: ValidateResponse;
}

export interface GhostPreview {
  productId: string;
  pose: Pose;
  label: string;
}

interface UiState {
  tool: Tool;
  selectedId: string | null;
  selectedOpeningId: string | null;
  fitCounter: number; // bump to ask the canvas to re-fit
  zoomNudge: number; // +1 / -1 requests
  zoomPct: number; // published by the canvas (100 = 1px per cm)

  guideSheetOpen: boolean;
  productsSheetOpen: boolean;
  cartOpen: boolean;
  summaryOpen: boolean;
  renderOpen: boolean;
  view3DOpen: boolean;
  prefsOpen: boolean;
  shareOpen: boolean;
  checkoutOpen: boolean;
  leftPanelOpen: boolean;

  toasts: Toast[];
  warning: ActiveWarning | null;
  ghost: GhostPreview | null;
  pendingValidation: string | null; // instance id being validated
  itemIssues: Record<string, "error" | "warning">; // badge dots after bulk revalidation
  doorWidth: number;
  windowWidth: number;

  setTool: (tool: Tool) => void;
  select: (id: string | null) => void;
  selectOpening: (id: string | null) => void;
  requestFit: () => void;
  nudgeZoom: (dir: 1 | -1) => void;
  setSheet: (
    key:
      | "guideSheetOpen"
      | "productsSheetOpen"
      | "cartOpen"
      | "summaryOpen"
      | "renderOpen"
      | "view3DOpen"
      | "prefsOpen"
      | "shareOpen"
      | "checkoutOpen"
      | "leftPanelOpen",
    value: boolean,
  ) => void;
  toast: (kind: Toast["kind"], message: string) => void;
  dismissToast: (id: number) => void;
  setWarning: (warning: ActiveWarning | null) => void;
  setGhost: (ghost: GhostPreview | null) => void;
  setPendingValidation: (id: string | null) => void;
  setItemIssues: (issues: Record<string, "error" | "warning">) => void;
  setOpeningWidth: (kind: "door" | "window", width: number) => void;
  setZoomPct: (pct: number) => void;
}

let toastId = 0;

export const useUiStore = create<UiState>((set) => ({
  tool: "select",
  selectedId: null,
  selectedOpeningId: null,
  fitCounter: 0,
  zoomNudge: 0,
  zoomPct: 100,

  guideSheetOpen: false,
  productsSheetOpen: false,
  cartOpen: false,
  summaryOpen: false,
  renderOpen: false,
  view3DOpen: false,
  prefsOpen: false,
  shareOpen: false,
  checkoutOpen: false,
  leftPanelOpen: false,

  toasts: [],
  warning: null,
  ghost: null,
  pendingValidation: null,
  itemIssues: {},
  doorWidth: 90,
  windowWidth: 150,

  setTool: (tool) => set({ tool, selectedId: null, selectedOpeningId: null, warning: null }),
  select: (selectedId) => set({ selectedId, selectedOpeningId: null }),
  selectOpening: (selectedOpeningId) => set({ selectedOpeningId, selectedId: null }),
  requestFit: () => set((s) => ({ fitCounter: s.fitCounter + 1 })),
  nudgeZoom: (dir) => set((s) => ({ zoomNudge: s.zoomNudge + dir })),

  setSheet: (key, value) => set({ [key]: value } as Partial<UiState>),

  toast: (kind, message) =>
    set((s) => {
      const id = ++toastId;
      setTimeout(() => {
        set((cur) => ({ toasts: cur.toasts.filter((t) => t.id !== id) }));
      }, 4500);
      return { toasts: [...s.toasts.slice(-3), { id, kind, message }] };
    }),

  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  setWarning: (warning) => set({ warning }),
  setGhost: (ghost) => set({ ghost }),
  setPendingValidation: (pendingValidation) => set({ pendingValidation }),
  setItemIssues: (itemIssues) => set({ itemIssues }),
  setOpeningWidth: (kind, width) =>
    set(kind === "door" ? { doorWidth: width } : { windowWidth: width }),
  setZoomPct: (zoomPct) => set({ zoomPct }),
}));
