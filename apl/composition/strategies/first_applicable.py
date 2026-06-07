from __future__ import annotations

from apl.types import Decision, Verdict

from .base_strategy import BaseCompositionStrategy


class FirstApplicableStrategy(BaseCompositionStrategy):
    """
    The first policy that takes a position wins.

    OBSERVE verdicts abstain and are skipped. When ``CompositionConfig.priority`` is
    set, verdicts are considered in that policy-name order (first name = highest
    priority) rather than arrival order; policies absent from the list keep their
    original relative order behind the ranked ones. With no priority configured this is
    plain arrival order.
    """

    def compose(self, verdicts: list[Verdict]) -> Verdict:
        guard = self._guard_empty_verdicts(verdicts)
        if guard is not None:
            return guard

        ordered = self._order_by_priority(verdicts)
        all_mods = self._collect_all_modifications(ordered)

        for verdict in ordered:
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

        return Verdict.allow(reasoning="No applicable policy")

    def _order_by_priority(self, verdicts: list[Verdict]) -> list[Verdict]:
        priority = self._config.priority
        if not priority:
            return verdicts
        rank = {name: index for index, name in enumerate(priority)}
        unranked = len(priority)
        # sorted() is stable, so unranked verdicts (all keyed to `unranked`)
        # keep their original relative order behind the prioritised ones.
        return sorted(verdicts, key=lambda v: rank.get(v.policy_name, unranked))
