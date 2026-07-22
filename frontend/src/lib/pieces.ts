/**
 * Living-room piece checklist — mirrors the backend `pieces.py` (LIVING ROOM only; the backend
 * gates the checklist to living rooms). Pure data: no React, no store access.
 *
 * Each entry is one row in the "what to include" checklist. `key` is the exact backend key sent
 * in `Preferences.included_pieces`; `tier` decides pre-checked (essential) vs opt-in (optional).
 * Icons come from `lucide-react` (already a dependency).
 */
import {
  Grid2x2,
  Table,
  Tv,
  LampFloor,
  Armchair,
  UtensilsCrossed,
  SquareStack,
  Archive,
  Sprout,
  Flower2,
  type LucideIcon,
} from "lucide-react";

export type PieceTier = "essential" | "optional";

export interface PieceOption {
  key: string; // exact backend key (Preferences.included_pieces entries)
  label: string; // human-readable checklist label
  tier: PieceTier; // essential = pre-checked, optional = opt-in
  icon: LucideIcon; // lucide-react icon component
}

/** Ordered living-room checklist: essentials first (pre-checked), then optional add-ons. */
export const LIVING_ROOM_PIECES: PieceOption[] = [
  // Essentials — pre-checked by default.
  { key: "rug", label: "Rug", tier: "essential", icon: Grid2x2 },
  { key: "coffee_table", label: "Coffee Table", tier: "essential", icon: Table },
  { key: "tv_unit", label: "TV Unit", tier: "essential", icon: Tv },
  { key: "floor_lamp", label: "Floor Lamp", tier: "essential", icon: LampFloor },
  // Optional — opt-in.
  { key: "chaise_lounge", label: "Chaise Lounge", tier: "optional", icon: Armchair },
  { key: "dining_set", label: "Dining Set", tier: "optional", icon: UtensilsCrossed },
  { key: "side_table", label: "Side Table", tier: "optional", icon: SquareStack },
  { key: "console", label: "Console", tier: "optional", icon: Archive },
  { key: "plant", label: "Plant", tier: "optional", icon: Sprout },
  { key: "vases", label: "Vases", tier: "optional", icon: Flower2 },
];

/** The default checklist (essentials only) as backend keys — the pre-checked selection. */
export function defaultIncludedPieces(): string[] {
  return LIVING_ROOM_PIECES.filter((p) => p.tier === "essential").map((p) => p.key);
}

// --- sofa footprint choice (Preferences.sofa_type) ---

export type SofaType = "auto" | "2-seater" | "3-seater" | "l-shape";

export interface SofaTypeOption {
  value: SofaType;
  label: string;
}

export const SOFA_TYPE_OPTIONS: SofaTypeOption[] = [
  { value: "auto", label: "Auto" },
  { value: "2-seater", label: "2-Seater" },
  { value: "3-seater", label: "3-Seater" },
  { value: "l-shape", label: "L-Shape" },
];

// --- seating capacity bounds (Preferences.seating_capacity) ---

export const SEAT_COUNT_MIN = 2;
export const SEAT_COUNT_MAX = 10;
