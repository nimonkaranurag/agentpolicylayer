from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class AllowOverridesStrategy(BaseCompositionStrategy):
    def compose(self, verdicts: list[Verdict]) -> Verdict:
        # Empty input means no policy had an opinion (unavailability is already
        # converted to an in-list deny upstream by the fail-closed client), so
        # allow — matching every other strategy. Previously this denied, an LSP
        # surprise when swapping strategies.
        guard = self._guard_empty_verdicts(verdicts)
        if guard is not None:
            return guard

        all_mods = self._collect_all_modifications(verdicts)

        allow = self._find_first_verdict_with_decision(verdicts, Decision.ALLOW)
        if allow is not None:
            if all_mods:
                return Verdict(
                    decision=Decision.MODIFY,
                    reasoning=allow.reasoning,
                    modifications=all_mods,
                )
            return allow

        modified = self._build_modified_verdict(verdicts)
        if modified is not None:
            return modified

        escalate = self._find_first_verdict_with_decision(verdicts, Decision.ESCALATE)
        if escalate is not None:
            return escalate

        deny = self._find_first_verdict_with_decision(verdicts, Decision.DENY)
        if deny is not None:
            return deny

        return Verdict.deny(reasoning="No policy allowed")
