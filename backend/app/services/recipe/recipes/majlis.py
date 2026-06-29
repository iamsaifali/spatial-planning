"""Saudi Majlis recipe — mirrors the current MAJLIS_SEQUENCE exactly.

Role order == category order in app/services/guide/flow.py::MAJLIS_SEQUENCE
(sofa, rug, coffee_table, side_table, lighting, storage, decor, accent_chair).

perimeter_seating is the only multi-instance role: count=until_target reproduces the
current orchestrator's seating-capacity loop. Every other role is a single placement,
exactly as the planner does today.
"""

from app.services.recipe.models import CountRule, Recipe
from app.services.recipe.recipes import role

MAJLIS_RECIPE = Recipe(
    recipe_id="majlis.standard",
    room_type="majlis",
    focal_strategy="none",
    room_goals=["maximize_seating", "keep_center_open", "symmetry"],
    roles=[
        role(
            "perimeter_seating", "sofa", "perimeter_walls",
            ["against_wall", "not_block_door", "not_block_window"],
            count=CountRule(
                mode="until_target", metric="seating_capacity",
                source="pref_or_area_default", one_per="wall_segment",
                guards=["keep_center_open", "budget_reserve"],
            ),
            essential=True,
            scoring={"luxury": 0.2, "seating": 0.3},
        ),
        role("floor_anchor", "rug", "center_area", ["centered"]),
        role("focal_surface", "coffee_table", "center_area",
             ["centered", "min_clearance"], depends_on=["floor_anchor"]),
        role("support_surface", "side_table", "beside_anchor",
             depends_on=["perimeter_seating"]),
        role("ambient_light", "lighting", "corners"),
        role("storage", "storage", "remaining_wall", ["not_block_door"]),
        role("accent", "decor", "corners"),
        role("comfort_fill", "accent_chair", "beside_anchor",
             depends_on=["perimeter_seating"]),
    ],
)
