from apl.types import CompositionConfig, Verdict

from .strategies import (
    CompositionStrategy,
    get_strategy,
)


class VerdictComposer:
    def __init__(
        self, config: CompositionConfig | None = None
    ):
        self._config = config or CompositionConfig()
        self._strategy = get_strategy(
            self._config.mode
        )

    @property
    def config(self) -> CompositionConfig:
        return self._config

    @property
    def strategy(self) -> CompositionStrategy:
        return self._strategy

    def compose(
        self, verdicts: list[Verdict]
    ) -> Verdict:
        return self._strategy.compose(verdicts)
