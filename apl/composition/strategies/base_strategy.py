from __future__ import annotations

from typing import Protocol

from apl.types import Decision, Verdict


class CompositionStrategy(Protocol):

    def compose(
        self, verdicts: list[Verdict]
    ) -> Verdict: ...


class BaseCompositionStrategy:

    @staticmethod
    def _find_first_verdict_with_decision(
        verdicts: list[Verdict],
        decision: Decision,
    ) -> Verdict | None:
        for verdict in verdicts:
            if verdict.decision == decision:
                return verdict
        return None

    @staticmethod
    def _guard_empty_verdicts(
        verdicts: list[Verdict],
        fallback_reasoning: str = "No policies evaluated",
    ) -> Verdict | None:
        if not verdicts:
            return Verdict.allow(
                reasoning=fallback_reasoning
            )
        return None
