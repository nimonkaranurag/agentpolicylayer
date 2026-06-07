from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class UnanimousStrategy(BaseCompositionStrategy):
    """
    Consensus gate: every policy that takes a position must ALLOW.

    OBSERVE verdicts abstain and are ignored. If no policy takes a position — an empty
    verdict set or all-observe — there is nothing to veto, so the action is allowed;
    this keeps empty-input behaviour consistent with the other strategies. Any non-allow
    position (deny, modify, or escalate) breaks unanimity, and the composed verdict is a
    deny that records the dissent.

    This is deliberately *not* deny-overrides: under deny-overrides a lone ``modify`` or
    ``escalate`` would carry through, but unanimity treats either as a failure to reach
    consensus and denies.
    """

    def compose(self, verdicts: list[Verdict]) -> Verdict:
        positions = [v for v in verdicts if v.decision != Decision.OBSERVE]
        if not positions:
            return Verdict.allow(reasoning="No policy objected")

        dissenters = [v for v in positions if v.decision != Decision.ALLOW]
        if not dissenters:
            return Verdict.allow(reasoning="All policies agreed")

        return Verdict.deny(reasoning=self._summarize_dissent(dissenters))

    @staticmethod
    def _summarize_dissent(dissenters: list[Verdict]) -> str:
        reasons = [v.reasoning for v in dissenters if v.reasoning]
        if reasons:
            return "Not unanimous: " + "; ".join(reasons)
        decisions = sorted({v.decision.value for v in dissenters})
        return "Not unanimous: " + ", ".join(decisions)
