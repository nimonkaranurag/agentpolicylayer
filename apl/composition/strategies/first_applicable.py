from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class FirstApplicableStrategy(BaseCompositionStrategy):

    def compose(self, verdicts: list[Verdict]) -> Verdict:
        guard: Verdict | None = self._guard_empty_verdicts(
            verdicts
        )
        if guard is not None:
            return guard

        for verdict in verdicts:
            if verdict.decision != Decision.OBSERVE:
                return verdict

        return Verdict.allow(
            reasoning="No applicable policy"
        )
