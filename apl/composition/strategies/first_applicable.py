from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class FirstApplicableStrategy(BaseCompositionStrategy):

    def compose(
        self, verdicts: list[Verdict]
    ) -> Verdict:
        guard = self._guard_empty_verdicts(verdicts)
        if guard is not None:
            return guard

        all_mods = self._collect_all_modifications(
            verdicts
        )

        for verdict in verdicts:
            if verdict.decision == Decision.OBSERVE:
                continue

            if all_mods and verdict.decision in (
                Decision.ALLOW,
                Decision.MODIFY,
            ):
                return Verdict(
                    decision=Decision.MODIFY,
                    reasoning=verdict.reasoning,
                    modifications=all_mods,
                    escalation=verdict.escalation,
                )
            return verdict

        return Verdict.allow(
            reasoning="No applicable policy"
        )
