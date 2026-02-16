from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class WeightedStrategy(BaseCompositionStrategy):

    def compose(
        self, verdicts: list[Verdict]
    ) -> Verdict:
        guard = self._guard_empty_verdicts(verdicts)
        if guard is not None:
            return guard

        all_mods = self._collect_all_modifications(
            verdicts
        )

        escalate = (
            self._find_first_verdict_with_decision(
                verdicts, Decision.ESCALATE
            )
        )
        if escalate is not None:
            return escalate

        allow_score = sum(
            v.confidence
            for v in verdicts
            if v.decision == Decision.ALLOW
        )
        deny_score = sum(
            v.confidence
            for v in verdicts
            if v.decision == Decision.DENY
        )

        if deny_score > allow_score:
            deny = (
                self._find_first_verdict_with_decision(
                    verdicts, Decision.DENY
                )
            )
            if deny is not None:
                return deny
            return Verdict.deny(
                reasoning=f"Weighted deny ({deny_score:.2f} vs {allow_score:.2f})"
            )

        if all_mods:
            return Verdict(
                decision=Decision.MODIFY,
                reasoning=f"Weighted allow ({allow_score:.2f} vs {deny_score:.2f})",
                modifications=all_mods,
            )

        return Verdict.allow(
            reasoning=f"Weighted allow ({allow_score:.2f} vs {deny_score:.2f})"
        )
