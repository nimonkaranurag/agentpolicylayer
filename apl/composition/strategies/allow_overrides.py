from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy

PRIORITY_ORDER: list[Decision] = [
    Decision.ALLOW,
    Decision.MODIFY,
    Decision.ESCALATE,
    Decision.DENY,
]


class AllowOverridesStrategy(BaseCompositionStrategy):

    def compose(self, verdicts: list[Verdict]) -> Verdict:
        if not verdicts:
            return Verdict.deny(
                reasoning="No policies evaluated"
            )

        for decision in PRIORITY_ORDER:
            match: Verdict | None = (
                self._find_first_verdict_with_decision(
                    verdicts,
                    decision,
                )
            )
            if match is not None:
                return match

        return Verdict.deny(reasoning="No policy allowed")
