"""Recipe strategy registry - maps strategy NAMES to real spatial strategy handlers.

Phase 4: the handlers live in app/services/spatial/strategies.py and call the specific
geometry generators directly, so the recipe path no longer routes its zone generation
through the room_type/category dispatch (zones_for_category). resolve_strategy is the
single lookup the interpreter uses.
"""

from dataclasses import dataclass

from spatial_planning.services.spatial.strategies import SPATIAL_STRATEGIES, ZoneStrategyFn


@dataclass(frozen=True)
class ZoneStrategy:
    name: str
    resolver: ZoneStrategyFn


STRATEGY_REGISTRY: dict[str, ZoneStrategy] = {
    name: ZoneStrategy(name=name, resolver=fn) for name, fn in SPATIAL_STRATEGIES.items()
}


def resolve_strategy(name: str) -> ZoneStrategy:
    strategy = STRATEGY_REGISTRY.get(name)
    if strategy is None:
        raise KeyError(f"Unknown zone-strategy reference '{name}'")
    return strategy
