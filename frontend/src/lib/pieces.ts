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
  Lamp,
  Shirt,
  Laptop,
  Sofa,
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

/**
 * Bedroom piece checklist — mirrors the backend bedroom piece table in `pieces.py`.
 * The bed is core (always placed, not a checklist row). Essentials are pre-checked;
 * the dressing table and reading chair are opt-in add-ons.
 */
export const BEDROOM_PIECES: PieceOption[] = [
  // Essentials — pre-checked by default.
  { key: "nightstands", label: "Nightstands", tier: "essential", icon: SquareStack },
  { key: "wardrobe", label: "Wardrobe", tier: "essential", icon: Shirt },
  { key: "rug", label: "Rug", tier: "essential", icon: Grid2x2 },
  { key: "bedside_lamp", label: "Bedside Lamp", tier: "essential", icon: Lamp },
  // Optional — opt-in.
  { key: "dressing_table", label: "Dressing Table", tier: "optional", icon: Table },
  { key: "reading_chair", label: "Reading Chair", tier: "optional", icon: Armchair },
  { key: "work_nook", label: "Work Nook", tier: "optional", icon: Laptop },
  { key: "tv_unit", label: "TV Unit", tier: "optional", icon: Tv },
  { key: "floor_lamp", label: "Floor Lamp", tier: "optional", icon: LampFloor },
  { key: "plant", label: "Plant", tier: "optional", icon: Sprout },
  { key: "lounge_sofa", label: "Sofa", tier: "optional", icon: Sofa },
  { key: "center_table", label: "Center Table", tier: "optional", icon: Table },
];

/** Bedroom default checklist (essentials only) as backend keys. */
export function defaultIncludedBedroomPieces(): string[] {
  return BEDROOM_PIECES.filter((p) => p.tier === "essential").map((p) => p.key);
}

/** The piece checklist + its essentials-only default for a room type. */
export function piecesForRoom(roomType: string | null): {
  pieces: PieceOption[];
  defaults: string[];
} {
  if (roomType === "bedroom") {
    return { pieces: BEDROOM_PIECES, defaults: defaultIncludedBedroomPieces() };
  }
  return { pieces: LIVING_ROOM_PIECES, defaults: defaultIncludedPieces() };
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

// --- bed size choice (Preferences.bed_size) ---

export type BedSize = "auto" | "single" | "double" | "queen" | "king";

export interface BedSizeOption {
  value: BedSize;
  label: string;
}

export const BED_SIZE_OPTIONS: BedSizeOption[] = [
  { value: "auto", label: "Auto" },
  { value: "single", label: "Single" },
  { value: "double", label: "Double" },
  { value: "queen", label: "Queen" },
  { value: "king", label: "King" },
];

// --- seating capacity bounds (Preferences.seating_capacity) ---

export const SEAT_COUNT_MIN = 2;
export const SEAT_COUNT_MAX = 10;
