from typing import Protocol

from apl.types import Verdict


class CompositionStrategy(Protocol):
    def compose(self, verdicts: list[Verdict]) -> Verdict: ...
