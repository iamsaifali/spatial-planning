import type { Room } from "@/types/api";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export const API_V1 = `${API_BASE}/api/v1`;

// Keyed by string (not Category): only the 10 placement-role keys are ever looked up here
// (guide steps / tabs), while products may carry richer store categories that never index this.
export const CATEGORY_LABELS: Record<string, string> = {
  sofa: "Sofa",
  tv_unit: "TV Unit",
  rug: "Rug",
  coffee_table: "Coffee Table",
  side_table: "Side Table",
  accent_chair: "Accent Chair",
  lighting: "Lighting",
  storage: "Storage",
  decor: "Decor",
  bed: "Bed",
  custom: "Your Item",
};

/** Plural category labels for the "All Sofas"-style tab (mockup parity). */
export const CATEGORY_PLURALS: Record<string, string> = {
  sofa: "Sofas",
  tv_unit: "TV Units",
  rug: "Rugs",
  coffee_table: "Coffee Tables",
  side_table: "Side Tables",
  accent_chair: "Accent Chairs",
  lighting: "Lighting",
  storage: "Storage",
  decor: "Decor",
  bed: "Beds",
  custom: "Your Items",
};

/** Store category -> placement role (mirror of the backend PLACEMENT_GROUP). Products carry
 *  real store categories (e.g. "3-seater-sofa"); the guide steps / labels use the 10 roles,
 *  so map through this before any CATEGORY_LABELS lookup or setCurrentStep call. */
export const PLACEMENT_GROUP: Record<string, string> = {
  "2-seater-sofa": "sofa", "3-seater-sofa": "sofa", "l-shape-sofa": "sofa", "chaise-lounge": "sofa",
  chair: "accent_chair", "office-chair": "accent_chair",
  "tv-table": "tv_unit", "center-table": "coffee_table",
  "side-table": "side_table", "service-table": "side_table", carpet: "rug",
  console: "storage", shelve: "storage", "storage-box": "storage", wardrobe: "storage", "dressing-table": "storage",
  "wall-lighting": "lighting", lampshade: "lighting", "floor-stand": "lighting",
  "art-canvas": "decor", "decorative-hanger": "decor", "flower-pot-and-plant": "decor",
  flower: "decor", vase: "decor", "statue-and-antique": "decor", "wall-clock": "decor",
};

/** The placement role for a (possibly store-specific) category. Identity for the 10 roles. */
export function placementRole(category: string): string {
  return PLACEMENT_GROUP[category] ?? category;
}

/** A human-readable name for any category (role or store), e.g. "3-seater-sofa" -> "3-Seater
 *  Sofa", "tv-table" -> "TV Table", "console" -> "Console". Used for the selected-item chip. */
const CATEGORY_DISPLAY_SPECIAL: Record<string, string> = {
  "tv-table": "TV Table",
  "2-seater-sofa": "2-Seater Sofa",
  "3-seater-sofa": "3-Seater Sofa",
  "l-shape-sofa": "L-Shape Sofa",
};
export function categoryName(category: string): string {
  return (
    CATEGORY_DISPLAY_SPECIAL[category] ??
    CATEGORY_LABELS[category] ??
    category
      .split(/[-_]/)
      .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
      .join(" ")
  );
}

/** Reason-code phrases mirrored from the backend zone engine. */
export const REASON_PHRASES: Record<string, string> = {
  longest_clear_wall: "longest clear wall",
  keeps_entry_path_open: "keeps walkways clear",
  faces_focal_wall: "faces the focal wall",
  near_window: "partly under a window",
  tight_space: "compact sizes fit best",
  faces_sofa: "directly faces the sofa",
  ideal_viewing_distance: "comfortable viewing distance",
  anchors_seating_zone: "anchors the seating zone",
  front_legs_on_rug: "ties the seating together",
  within_easy_reach: "within easy reach",
  conversation_angle: "angled for conversation",
  corner_near_seating: "lights the seating corner",
  uses_remaining_wall: "uses a free wall",
  flexible_spot: "out of walking paths",
  secondary_zone: "completes a second seating area",
  headboard_to_wall: "headboard against the wall",
  media_at_viewing_distance: "at a comfortable viewing distance",
};

export const STYLE_LABELS: Record<string, string> = {
  modern: "Modern",
  scandinavian: "Scandinavian",
  industrial: "Industrial",
  boho: "Boho",
  classic: "Classic",
  minimal: "Minimal",
  arabic: "Arabic",
  saudi_traditional: "Saudi Traditional",
  majlis: "Majlis",
  modern_arabic: "Modern Arabic",
  luxury: "Luxury",
};

/** Solid furniture tints for the canvas top views (warm only). */
export const COLOR_FILLS: Record<string, string> = {
  beige: "#D9CDB8",
  ivory: "#F0EAD9",
  "warm grey": "#B8B2A9",
  charcoal: "#4A4540",
  oat: "#E3D9C3",
  sand: "#DECFB2",
  oak: "#C9A876",
  walnut: "#8A6748",
  teak: "#A87E51",
  sheesham: "#7E5A3C",
  "mango wood": "#B98D5F",
  olive: "#8A8A5C",
  rust: "#B0603F",
  terracotta: "#C07050",
  "forest green": "#5F7350",
  mustard: "#C8963E",
  clay: "#B5765A",
  brass: "#C8963E",
  black: "#3A3531",
  white: "#F4F1EA",
};

export function productFill(colors: string[]): string {
  for (const color of colors) {
    const fill = COLOR_FILLS[color.toLowerCase()];
    if (fill) return fill;
  }
  return "#D9CDB8";
}

/** The mockup-style starter room: 4.8 x 3.6 m, door top-left, window bottom. */
export function sampleRoom(): Room {
  return {
    vertices: [
      [0, 0],
      [480, 0],
      [480, 360],
      [0, 360],
    ],
    doors: [
      { id: "door-1", wall_index: 0, offset_cm: 40, width_cm: 90, height_cm: 210, swing: "inward", hinge: "left" },
    ],
    windows: [
      { id: "window-1", wall_index: 2, offset_cm: 150, width_cm: 180, sill_height_cm: 90, height_cm: 120 },
    ],
    wall_height_cm: 270,
  };
}

export function emptyRectRoom(widthCm: number, depthCm: number): Room {
  return {
    vertices: [
      [0, 0],
      [widthCm, 0],
      [widthCm, depthCm],
      [0, depthCm],
    ],
    doors: [],
    windows: [],
    wall_height_cm: 270,
  };
}

export function lShapeRoom(): Room {
  return {
    vertices: [
      [0, 0],
      [560, 0],
      [560, 300],
      [320, 300],
      [320, 480],
      [0, 480],
    ],
    doors: [],
    windows: [],
    wall_height_cm: 270,
  };
}

export const DOOR_WIDTH_PRESETS = [80, 90, 120];
export const WINDOW_WIDTH_PRESETS = [100, 150, 200];

export const GRID_CM = 10;
export const MIN_WALL_CM = 60;
export const MIN_ZOOM = 0.12;
export const MAX_ZOOM = 4;
