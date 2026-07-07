"""Style + colour vocabulary for product metadata and preference-based matching.

The demo catalog carries per-product `styles`, `main_color`, `secondary_colors` (generated
upstream). This module is the single source of truth for:
  - the valid STYLE names (mirrors the room-redesign `room_style` vocabulary), and
  - the colour -> palette FAMILY mapping (so a product's `main_color` snaps to a `main_family`
    bucket the recommender can match a room's palette against).

Tone and per-secondary families are intentionally NOT modelled: matching keys off `main_family`.
"""

from __future__ import annotations

# Aesthetic style names (superset of the room-redesign room_style list + the extras the
# catalog actually uses). A product may carry several.
STYLES: list[str] = [
    "Modern", "Contemporary", "Minimalist", "Boho", "Industrial", "Classy",
    "Modern_Classic", "Rustic_Modern", "Eclectic", "Zen", "Shabby_Chic",
    "Islamic", "Tropical", "Scandinavian", "Mid_Century", "Japandi", "Coastal",
    "Traditional", "Moroccan",
]

# The palette buckets the recommender matches on.
COLOR_FAMILIES: list[str] = [
    "Warm Neutral", "Cool Neutral", "Monochrome", "Earthy/Terracotta",
    "Wood/Natural", "Jewel Tones", "Pastel/Soft", "Bold/Vibrant",
    "Blue", "Green", "Metallic/Gold",
]

# Named colour -> palette family. Covers every value the catalog uses (main + secondary).
COLOR_TO_FAMILY: dict[str, str] = {
    # Neutrals
    "White": "Monochrome", "Ivory": "Warm Neutral", "Beige": "Warm Neutral",
    "Taupe": "Warm Neutral", "Sand": "Warm Neutral", "Greige": "Cool Neutral",
    "Light Grey": "Cool Neutral", "Grey": "Cool Neutral", "Charcoal": "Monochrome",
    "Black": "Monochrome",
    # Wood & brown
    "Oak": "Wood/Natural", "Walnut": "Wood/Natural", "Espresso": "Wood/Natural",
    "Clay": "Earthy/Terracotta", "Terracotta": "Earthy/Terracotta", "Olive": "Earthy/Terracotta",
    # Warm / bold
    "Mustard": "Bold/Vibrant", "Burnt Orange": "Bold/Vibrant",
    # Metallic
    "Gold": "Metallic/Gold", "Brass": "Metallic/Gold", "Bronze": "Metallic/Gold",
    # Green
    "Sage": "Green", "Forest Green": "Green",
    # Blue
    "Powder Blue": "Blue", "Denim Blue": "Blue", "Navy": "Blue",
    # Jewel
    "Teal": "Jewel Tones", "Emerald": "Jewel Tones", "Sapphire": "Jewel Tones",
    "Ruby": "Jewel Tones", "Plum": "Jewel Tones",
    # Pastel
    "Blush": "Pastel/Soft", "Lavender": "Pastel/Soft",
}


def family_of(color_name: str) -> str:
    """Palette family for a named colour (``""`` if unknown, so callers can skip it)."""
    return COLOR_TO_FAMILY.get((color_name or "").strip(), "")
