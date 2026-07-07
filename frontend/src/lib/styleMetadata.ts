// User-facing style + colour-family vocabulary — mirrors backend app/models/style_metadata.py.
// Drives the "Pick your style" step and the Preferences.style / color_families sent to /assist/layout.

export const STYLES = [
  "Modern",
  "Contemporary",
  "Minimalist",
  "Scandinavian",
  "Japandi",
  "Mid_Century",
  "Boho",
  "Coastal",
  "Tropical",
  "Industrial",
  "Rustic_Modern",
  "Eclectic",
  "Zen",
  "Classy",
  "Modern_Classic",
  "Traditional",
  "Shabby_Chic",
  "Islamic",
  "Moroccan",
] as const;

export const COLOR_FAMILIES = [
  "Warm Neutral",
  "Cool Neutral",
  "Monochrome",
  "Wood/Natural",
  "Earthy/Terracotta",
  "Blue",
  "Green",
  "Jewel Tones",
  "Pastel/Soft",
  "Bold/Vibrant",
  "Metallic/Gold",
] as const;

// A representative swatch colour per family for the picker chips.
export const FAMILY_SWATCH: Record<string, string> = {
  "Warm Neutral": "#D9C7A7",
  "Cool Neutral": "#C3C7CC",
  Monochrome: "#3A3A3A",
  "Wood/Natural": "#9C6B3F",
  "Earthy/Terracotta": "#B5651D",
  Blue: "#2F5D8A",
  Green: "#4A7A4A",
  "Jewel Tones": "#4B2E5E",
  "Pastel/Soft": "#E7C6D4",
  "Bold/Vibrant": "#E4572E",
  "Metallic/Gold": "#C9A24B",
};

// "Mid_Century" -> "Mid Century" for display.
export const styleLabel = (s: string): string => s.replace(/_/g, " ");
