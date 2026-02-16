from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class DenyOverridesStrategy(BaseCompositionStrategy):

    def __init__(
        self,
        allow_reasoning: str = "All policies allowed",
    ) -> None:
        self._allow_reasoning = allow_reasoning

    def compose(
        self, verdicts: list[Verdict]
    ) -> Verdict:

        guard = self._guard_empty_verdicts(verdicts)
        if guard is not None:
            return guard

        deny = self._find_first_verdict_with_decision(
            verdicts, Decision.DENY
        )
        if deny is not None:
            return deny

        escalate = (
            self._find_first_verdict_with_decision(
                verdicts, Decision.ESCALATE
            )
        )
        if escalate is not None:
            return escalate

        modified = self._build_modified_verdict(
            verdicts
        )
        if modified is not None:
            return modified

        return Verdict.allow(
            reasoning=self._allow_reasoning
        )
