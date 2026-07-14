"""Recipe schemas — DATA only.

A recipe is a declarative spec for furnishing one room type. It NAMES roles, their
dependency order, the reusable zone-strategy + predicates each role uses, count rules
and scoring hints. It is interpreted by the (unchanging) deterministic engine.

Hard rules (see the architecture blueprint):
  * recipes contain NO coordinates, geometry, placement algorithms, validation logic,
    product ids, or predicate/strategy IMPLEMENTATIONS;
  * recipes only REFERENCE named strategies (services/recipe/strategies.py) and named
    predicates (services/recipe/predicates.py), which remain code;
  * recipes are declarative — no control flow. If a recipe needs logic it has become a
    DSL, which is explicitly out of scope.
"""

from typing import Any, Literal

from pydantic import Field

from spatial_planning.models.geometry import StrictModel

# Count modes the engine understands. Phase 1 only uses "single" and "until_target"
# (those are what reproduce current behavior); the rest are reserved for later room
# types (mirror_pair for nightstands, fill_available for decor, etc.).
CountMode = Literal["single", "until_target", "fill_available", "mirror_pair", "per_anchor"]


class CountRule(StrictModel):
    """How many instances of a role to place, and when to stop.

    The recipe picks the MODE; the engine computes the NUMBER from room size / wall
    length / capacity target / budget, bounded by the named guards.
    """

    mode: CountMode = "single"
    metric: str | None = None  # target metric, e.g. "seating_capacity" (until_target)
    source: str | None = None  # where the target comes from, e.g. "pref_or_area_default"
    one_per: str | None = None  # granularity, e.g. "wall_segment" (one bench per wall)
    per_area_m2: float | None = Field(default=None, gt=0)  # fill_available: ~1 item per N m2
    max: int | None = Field(default=None, ge=1)  # sanity / zone cap
    guards: list[str] = Field(default_factory=list)  # stop conditions, e.g. ["keep_center_open"]


class ZoneStrategyRef(StrictModel):
    """Reference to a code-defined zone strategy (resolved via strategies.py)."""

    name: str  # must exist in strategies.STRATEGY_REGISTRY
    params: dict[str, Any] = Field(default_factory=dict)


class PredicateRef(StrictModel):
    """Reference to a code-defined predicate (resolved via predicates.py)."""

    name: str  # must exist in predicates.PREDICATE_REGISTRY
    args: dict[str, Any] = Field(default_factory=dict)


class RoleDefinition(StrictModel):
    """A functional slot in a room (function, NOT a catalog category).

    The same category ("sofa") can fill different roles in different rooms
    (primary_seating in a living room, perimeter_seating in a majlis) with different
    strategies — that decoupling is the point of roles.
    """

    role: str
    categories: list[str] = Field(min_length=1)  # catalog categories that can fill it
    zone_strategy: ZoneStrategyRef
    predicates: list[PredicateRef] = Field(default_factory=list)
    count: CountRule = Field(default_factory=CountRule)
    depends_on: list[str] = Field(default_factory=list)  # role ids this anchors to (graph edges)
    scoring: dict[str, float] = Field(default_factory=dict)  # weight nudges, applied later
    essential: bool = False  # if true and it can't be placed, the room is "incomplete"
    store_category: str | None = None  # pin this role to a specific STORE category (e.g. "vase"),
    # overriding the room's default preference for the placement group
    allow_duplicate: bool = False  # place even if this placement group is already present
    # (lets a 2nd decor role - e.g. vases on the console - run alongside the corner decor)


class Recipe(StrictModel):
    recipe_id: str
    version: str = "1.0.0"
    room_type: str
    focal_strategy: Literal["longest_wall", "window", "tv_wall", "none"] = "none"
    room_goals: list[str] = Field(default_factory=list)
    roles: list[RoleDefinition] = Field(min_length=1)

    def category_sequence(self) -> list[str]:
        """The primary-category placement order — used by the migration adapter to
        prove the recipe reproduces the live planner's sequence."""
        return [role.categories[0] for role in self.roles]
