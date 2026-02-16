from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class AllowOverridesStrategy(BaseCompositionStrategy):

    def compose(
        self, verdicts: list[Verdict]
    ) -> Verdict:
        if not verdicts:
            return Verdict.deny(
                reasoning="No policies evaluated"
            )

        all_mods = self._collect_all_modifications(
            verdicts
        )

        allow = self._find_first_verdict_with_decision(
            verdicts, Decision.ALLOW
        )
        if allow is not None:
            if all_mods:
                return Verdict(
                    decision=Decision.MODIFY,
                    reasoning=allow.reasoning,
                    modifications=all_mods,
                )
            return allow

        modified = self._build_modified_verdict(
            verdicts
        )
        if modified is not None:
            return modified

        escalate = (
            self._find_first_verdict_with_decision(
                verdicts, Decision.ESCALATE
            )
        )
        if escalate is not None:
            return escalate

        deny = self._find_first_verdict_with_decision(
            verdicts, Decision.DENY
        )
        if deny is not None:
            return deny

        return Verdict.deny(
            reasoning="No policy allowed"
        )
