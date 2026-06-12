"use client";

import { create } from "zustand";
import type { SceneConfig } from "@/types/api";

/** Geometry shared by the 2D canvas and the 3D view; served by /config (.env). */
interface SceneState {
  wallThicknessCm: number;
  applyConfig: (scene: SceneConfig) => void;
}

export const useSceneStore = create<SceneState>((set) => ({
  wallThicknessCm: 12, // fallback mirrors the backend default
  applyConfig: (scene) => set({ wallThicknessCm: scene.wall_thickness_cm }),
}));
