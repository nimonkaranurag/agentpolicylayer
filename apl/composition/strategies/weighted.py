from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class WeightedStrategy(BaseCompositionStrategy):
    """
    Confidence-weighted vote between allow and deny.

    Each verdict contributes ``weight × confidence`` to its decision's score, where
    ``weight`` is the per-policy value from ``CompositionConfig.weights`` (keyed by
    ``policy_name``) and defaults to 1.0 for any policy not listed. With no weights
    configured every weight is 1.0, so the score reduces to the sum of confidences. An
    escalation short-circuits to a human. Deny wins on a tie — allow must score strictly
    higher to overturn a deny — so the bias is toward enforcement.
    """

    def compose(self, verdicts: list[Verdict]) -> Verdict:
        guard = self._guard_empty_verdicts(verdicts)
        if guard is not None:
            return guard

        all_mods = self._collect_all_modifications(verdicts)

        escalate = self._find_first_verdict_with_decision(verdicts, Decision.ESCALATE)
        if escalate is not None:
            return escalate

        allow_score = self._score_for(verdicts, Decision.ALLOW)
        deny_score = self._score_for(verdicts, Decision.DENY)

        # Deny wins on a tie (>=), so the bias is toward enforcement: allow must
        # score *strictly* higher to overturn a deny. This also catches the
        # degenerate lone deny(confidence=0.0) case — 0 >= 0 with a deny present
        # denies rather than falling through to allow. The `any deny voted` guard
        # keeps an all-allow / all-modify set (deny_score 0, allow_score 0) from
        # being read as a deny.
        deny = self._find_first_verdict_with_decision(verdicts, Decision.DENY)
        if deny is not None and deny_score >= allow_score:
            return deny

        if all_mods:
            return Verdict(
                decision=Decision.MODIFY,
                reasoning=f"Weighted allow ({allow_score:.2f} vs {deny_score:.2f})",
                modifications=all_mods,
            )

        return Verdict.allow(
            reasoning=f"Weighted allow ({allow_score:.2f} vs {deny_score:.2f})"
        )

    def _score_for(self, verdicts: list[Verdict], decision: Decision) -> float:
        weights = self._config.weights
        total = 0.0
        for verdict in verdicts:
            if verdict.decision != decision:
                continue
            name = verdict.policy_name
            weight = weights.get(name, 1.0) if name is not None else 1.0
            total += weight * verdict.confidence
        return total
