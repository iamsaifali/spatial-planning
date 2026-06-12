"""Deterministic copy templates - full feature parity when no OpenAI key is set.

Every template consumes the SAME facts dict the LLM would receive, so offline
copy is grounded in identical spatial truths.
"""

from app.models.products import CATEGORY_LABELS


def _wall_phrase(facts: dict) -> str:
    label = facts.get("wall_label")
    return f"the {label} wall" if label else "the highlighted wall"


def _m(cm: float | None) -> str:
    return f"{(cm or 0) / 100:.1f} m"


GUIDE_INTROS = {
    "sofa": "Let's start with the main seating - the anchor of your living room.",
    "tv_unit": "Now let's give the seating a focal point with the TV unit.",
    "rug": "Next, a rug to visually define the seating zone.",
    "coffee_table": "Now we can add a coffee table within easy reach of the sofa.",
    "side_table": "Side tables keep essentials at arm's reach beside the sofa.",
    "accent_chair": "An accent chair adds an extra seat and completes the conversation circle.",
    "lighting": "Let's layer in lighting so the room works in the evening too.",
    "storage": "Some storage keeps everyday clutter out of sight.",
    "decor": "Finally, decor - the touches that make the room feel lived-in.",
}

REASON_PHRASES = {
    "longest_clear_wall": "it is your longest clear wall",
    "keeps_entry_path_open": "it keeps the walkway from the door open",
    "faces_focal_wall": "it faces the natural focal wall",
    "near_window": "note it sits partly under a window",
    "tight_space": "space is tight, so compact sizes will work best",
    "faces_sofa": "it sits directly opposite your sofa",
    "ideal_viewing_distance": "the viewing distance lands in the comfortable 2.5-4 m range",
    "anchors_seating_zone": "it anchors the seating zone you have built",
    "front_legs_on_rug": "the sofa's front legs will rest on it, which ties the zone together",
    "within_easy_reach": "it stays within easy reach of the seating",
    "conversation_angle": "it angles toward the sofa for easy conversation",
    "corner_near_seating": "the corner spot lights the seating without blocking movement",
    "uses_remaining_wall": "it makes use of a wall that is still free",
    "flexible_spot": "this spot stays out of the walking paths",
}


def guide_copy(facts: dict) -> dict:
    category = facts.get("category", "sofa")
    intro = GUIDE_INTROS.get(category, "Let's pick the next piece for your room.")
    reasons = [REASON_PHRASES[c] for c in facts.get("reason_codes", []) if c in REASON_PHRASES]
    zone_len = facts.get("zone_len_cm")

    parts = [intro]
    if facts.get("has_zone"):
        where = f"The best spot is along {_wall_phrase(facts)}" if facts.get("wall_label") else "I've highlighted the best spot on your canvas"
        if zone_len:
            where += f" - about {_m(zone_len)} of clear space"
        parts.append(where + ".")
        if reasons:
            parts.append("I recommend it because " + " and ".join(reasons[:2]) + ".")
    else:
        parts.append(
            "I couldn't find a comfortable spot for this in the current layout - "
            "you can skip this step or try a smaller piece."
        )

    tip = None
    if "near_window" in facts.get("reason_codes", []):
        tip = "Low-back pieces keep the window light flowing in."
    elif "tight_space" in facts.get("reason_codes", []):
        tip = "Compact or armless designs free up walking space in tighter rooms."
    elif category == "rug":
        tip = "A rug should extend roughly 30 cm beyond each side of the sofa."
    elif category == "coffee_table":
        tip = "Keep 40-45 cm between sofa and table - close enough to reach, far enough to walk."

    return {"message": " ".join(parts), "tip": tip}


def why_it_fits(facts: dict) -> dict:
    label = CATEGORY_LABELS.get(facts.get("category", ""), "piece").lower()
    name = facts.get("product_name", "This piece")
    util = facts.get("zone_utilization")
    style = facts.get("style_match", 0)

    why_product_bits = []
    if style and style >= 0.9:
        why_product_bits.append("matches your style preferences")
    elif style and style >= 0.5:
        why_product_bits.append("sits comfortably with the room's style")
    if facts.get("budget_fit", 0) >= 0.8:
        why_product_bits.append("fits your budget")
    if facts.get("rating", 0) >= 4.5:
        why_product_bits.append(f"is rated {facts['rating']} by buyers")
    why_product = f"{name} " + (", ".join(why_product_bits) if why_product_bits else "balances size, style and price for this room") + "."

    if util is not None:
        if util >= 0.85:
            why_size = f"It uses the zone fully ({facts.get('width_cm', 0):.0f} cm wide) - a generous fit with just enough breathing room."
        elif util >= 0.55:
            why_size = f"At {facts.get('width_cm', 0):.0f} cm wide it fills the zone comfortably without crowding it."
        else:
            why_size = f"Its compact {facts.get('width_cm', 0):.0f} cm width leaves plenty of open floor around it."
    else:
        why_size = "Its size suits the available space."

    overhang = facts.get("rug_overhang_per_side_cm")
    ratio = facts.get("table_to_sofa_ratio")
    arm_delta = facts.get("arm_height_delta_cm")
    if overhang is not None and overhang > 0:
        why_placement = f"It extends about {overhang:.0f} cm beyond the sofa on each side, which visually anchors the seating zone."
    elif ratio is not None:
        why_placement = "Its length is balanced against your sofa, keeping the seating area in proportion."
    elif arm_delta is not None and arm_delta <= 5:
        why_placement = "Its top lines up with the sofa armrest, so it reads as one piece."
    elif facts.get("wall_label"):
        why_placement = f"Placed along {_wall_phrase(facts)}, it keeps walkways clear."
    else:
        why_placement = "The suggested spot keeps door paths and walkways open."

    # prices stay on the product card - copy never embeds currency amounts
    return {"why_product": why_product, "why_size": why_size, "why_placement": why_placement}


def summary_narrative(facts: dict) -> dict:
    count = facts.get("item_count", 0)
    total = facts.get("total_price", 0)
    pct = facts.get("completeness_pct", 0)
    missing = facts.get("missing", [])
    area = facts.get("room_area_m2")

    bits = [
        f"Your {area:.0f} m2 living room now has {count} piece{'s' if count != 1 else ''} "
        f"and is {pct}% furnished." if area else f"Your room has {count} pieces and is {pct}% furnished."
    ]
    if missing:
        bits.append("Still worth adding: " + ", ".join(missing[:3]) + ".")
    else:
        bits.append("All the essentials are in place - a complete, livable layout.")
    if facts.get("issue_count", 0) == 0:
        bits.append("Walkways and door paths are clear.")
    else:
        bits.append(f"{facts['issue_count']} placement note{'s' if facts['issue_count'] != 1 else ''} to review on the canvas.")
    return {"narrative": " ".join(bits), "upgrade_pitch": None if not facts.get("upgrade_count") else "A couple of upgrades could lift the look further - see below."}


STEP_TIPS = {
    "sofa": "Anchor the sofa on the longest clear wall before anything else.",
    "tv_unit": "Aim for 2.5-4 m between sofa and screen.",
    "rug": "Front legs of all seating should rest on the rug.",
    "coffee_table": "40-45 cm from the sofa is the sweet spot.",
    "side_table": "Match the table height to the sofa armrest.",
    "accent_chair": "Angle it toward the sofa to invite conversation.",
    "lighting": "Place a floor lamp in a corner near the seating.",
    "storage": "Use a wall that is still free; keep 60 cm in front usable.",
    "decor": "Odd numbers of objects read more naturally than even.",
}


def assistant_offline(facts: dict) -> dict:
    room_bits = []
    if facts.get("room_area_m2"):
        room_bits.append(f"your room is about {facts['room_area_m2']:.0f} m2")
    if facts.get("placed_names"):
        room_bits.append("you have placed " + ", ".join(facts["placed_names"][:5]))
    if facts.get("completeness_pct") is not None:
        room_bits.append(f"the room is {facts['completeness_pct']}% furnished")
    summary = "; ".join(room_bits) if room_bits else "draw your room and start placing pieces"

    answer = (
        "The AI assistant is offline right now (no API key configured), but from the layout I can tell you: "
        + summary
        + "."
    )
    tip = STEP_TIPS.get(facts.get("step_key") or "", None)
    return {"answer": answer, "related_tip": tip}
