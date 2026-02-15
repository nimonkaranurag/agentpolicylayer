from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy

PRIORITY_ORDER: list[Decision] = [
    Decision.DENY,
    Decision.ESCALATE,
    Decision.MODIFY,
]


class DenyOverridesStrategy(BaseCompositionStrategy):

    def __init__(
        self, allow_reasoning: str = "All policies allowed"
    ) -> None:
        self._allow_reasoning: str = allow_reasoning

    def compose(self, verdicts: list[Verdict]) -> Verdict:
        guard: Verdict | None = self._guard_empty_verdicts(
            verdicts
        )
        if guard is not None:
            return guard

        for decision in PRIORITY_ORDER:
            match: Verdict | None = (
                self._find_first_verdict_with_decision(
                    verdicts,
                    decision,
                )
            )
            if match is not None:
                return match

        return Verdict.allow(
            reasoning=self._allow_reasoning
        )
