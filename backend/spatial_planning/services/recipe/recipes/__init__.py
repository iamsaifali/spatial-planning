"""Authored recipes + a small builder helper.

These recipes are DATA. They are authored to reproduce the current planner behaviour
exactly (same category order) — the migration adapter asserts that fidelity.
"""

from collections.abc import Sequence

from spatial_planning.services.recipe.models import (
    CountRule,
    PredicateRef,
    RoleDefinition,
    ZoneStrategyRef,
)


def role(
    name: str,
    category: str,
    strategy: str,
    predicates: Sequence[str] = (),
    *,
    params: dict | None = None,
    count: CountRule | None = None,
    depends_on: Sequence[str] = (),
    essential: bool = False,
    scoring: dict[str, float] | None = None,
    store_category: str | None = None,
    allow_duplicate: bool = False,
) -> RoleDefinition:
    """Readable constructor for a single-category role."""
    return RoleDefinition(
        role=name,
        categories=[category],
        zone_strategy=ZoneStrategyRef(name=strategy, params=params or {}),
        predicates=[PredicateRef(name=p) for p in predicates],
        count=count or CountRule(mode="single"),
        depends_on=list(depends_on),
        essential=essential,
        scoring=scoring or {},
        store_category=store_category,
        allow_duplicate=allow_duplicate,
    )
