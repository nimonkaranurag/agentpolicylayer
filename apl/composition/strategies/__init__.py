from __future__ import annotations

from typing import Callable, Dict

from apl.types import CompositionConfig, CompositionMode

from .allow_overrides import AllowOverridesStrategy
from .base_strategy import (
    BaseCompositionStrategy,
    CompositionStrategy,
)
from .deny_overrides import DenyOverridesStrategy
from .first_applicable import FirstApplicableStrategy
from .unanimous import UnanimousStrategy
from .weighted import WeightedStrategy

# Maps mode -> a factory that builds the strategy from the (optional) config. The
# strategies take config through their shared BaseCompositionStrategy constructor, so the
# registry is typed as the factory call site uses it.
StrategyFactory = Callable[[CompositionConfig | None], CompositionStrategy]

STRATEGY_REGISTRY: Dict[CompositionMode, StrategyFactory] = {
    CompositionMode.DENY_OVERRIDES: DenyOverridesStrategy,
    CompositionMode.ALLOW_OVERRIDES: AllowOverridesStrategy,
    CompositionMode.UNANIMOUS: UnanimousStrategy,
    CompositionMode.FIRST_APPLICABLE: FirstApplicableStrategy,
    CompositionMode.WEIGHTED: WeightedStrategy,
}


def get_strategy(
    mode: CompositionMode,
    config: CompositionConfig | None = None,
) -> CompositionStrategy:
    strategy_factory: StrategyFactory | None = STRATEGY_REGISTRY.get(mode)
    if strategy_factory is None:
        raise ValueError(f"Unknown composition mode: {mode}")
    return strategy_factory(config)


__all__: list[str] = [
    "CompositionStrategy",
    "BaseCompositionStrategy",
    "STRATEGY_REGISTRY",
    "get_strategy",
    "DenyOverridesStrategy",
    "AllowOverridesStrategy",
    "UnanimousStrategy",
    "FirstApplicableStrategy",
    "WeightedStrategy",
]
