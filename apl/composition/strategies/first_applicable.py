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

        # The *first* policy that takes a position wins, verbatim — including its
        # own modifications and nothing else. Aggregating every verdict's mods here
        # (the previous behaviour) meant a lower-priority policy, and even a
        # DENY-attached mod, leaked into a "first wins" MODIFY, so the first policy
        # did not actually win.
        for verdict in ordered:
            if verdict.decision == Decision.OBSERVE:
                continue
            return verdict

        return Verdict.allow(reasoning="No applicable policy")

    def _order_by_priority(self, verdicts: list[Verdict]) -> list[Verdict]:
        priority = self._config.priority
        if not priority:
            return verdicts
        rank = {name: index for index, name in enumerate(priority)}
        unranked = len(priority)

        def rank_of(verdict: Verdict) -> int:
            if verdict.policy_name is None:
                return unranked
            return rank.get(verdict.policy_name, unranked)

        # sorted() is stable, so unranked verdicts (all keyed to `unranked`)
        # keep their original relative order behind the prioritised ones.
        return sorted(verdicts, key=rank_of)
