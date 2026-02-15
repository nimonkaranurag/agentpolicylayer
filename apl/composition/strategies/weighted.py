from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class WeightedStrategy(BaseCompositionStrategy):

    def compose(self, verdicts: list[Verdict]) -> Verdict:
        guard: Verdict | None = self._guard_empty_verdicts(
            verdicts
        )
        if guard is not None:
            return guard

        allow_score: float = sum(
            v.confidence
            for v in verdicts
            if v.decision == Decision.ALLOW
        )
        deny_score: float = sum(
            v.confidence
            for v in verdicts
            if v.decision == Decision.DENY
        )

        if deny_score > allow_score:
            deny_verdict: Verdict | None = (
                self._find_first_verdict_with_decision(
                    verdicts,
                    Decision.DENY,
                )
            )
            if deny_verdict is not None:
                return deny_verdict
            return Verdict.deny(
                reasoning=f"Weighted deny ({deny_score:.2f} vs {allow_score:.2f})"
            )

        return Verdict.allow(
            reasoning=f"Weighted allow ({allow_score:.2f} vs {deny_score:.2f})"
        )
