from __future__ import annotations

from .deny_overrides import DenyOverridesStrategy


class UnanimousStrategy(DenyOverridesStrategy):

    def __init__(self) -> None:
        super().__init__(
            allow_reasoning="All policies agreed"
        )
