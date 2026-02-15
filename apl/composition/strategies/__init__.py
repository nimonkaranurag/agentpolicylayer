from __future__ import annotations

from typing import Dict, Type

from apl.types import CompositionMode

from .allow_overrides import AllowOverridesStrategy
from .base_strategy import (
    BaseCompositionStrategy,
    CompositionStrategy,
)
from .deny_overrides import DenyOverridesStrategy
from .first_applicable import FirstApplicableStrategy
from .unanimous import UnanimousStrategy
from .weighted import WeightedStrategy

STRATEGY_REGISTRY: Dict[
    CompositionMode, Type[CompositionStrategy]
] = {
    CompositionMode.DENY_OVERRIDES: DenyOverridesStrategy,
    CompositionMode.ALLOW_OVERRIDES: AllowOverridesStrategy,
    CompositionMode.UNANIMOUS: UnanimousStrategy,
    CompositionMode.FIRST_APPLICABLE: FirstApplicableStrategy,
    CompositionMode.WEIGHTED: WeightedStrategy,
}


def get_strategy(
    mode: CompositionMode,
) -> CompositionStrategy:
    strategy_class: Type[CompositionStrategy] | None = (
        STRATEGY_REGISTRY.get(mode)
    )
    if strategy_class is None:
        raise ValueError(
            f"Unknown composition mode: {mode}"
        )
    return strategy_class()


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
