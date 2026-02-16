from __future__ import annotations

from typing import Protocol

from apl.types import Decision, Modification, Verdict


class CompositionStrategy(Protocol):

    def compose(
        self, verdicts: list[Verdict]
    ) -> Verdict: ...


class BaseCompositionStrategy:

    @staticmethod
    def _find_first_verdict_with_decision(
        verdicts: list[Verdict],
        decision: Decision,
    ) -> Verdict | None:
        for verdict in verdicts:
            if verdict.decision == decision:
                return verdict
        return None

    @staticmethod
    def _guard_empty_verdicts(
        verdicts: list[Verdict],
        fallback_reasoning: str = "No policies evaluated",
    ) -> Verdict | None:
        if not verdicts:
            return Verdict.allow(
                reasoning=fallback_reasoning
            )
        return None

    @staticmethod
    def _collect_all_modifications(
        verdicts: list[Verdict],
    ) -> list[Modification]:
        by_target: dict[str, Modification] = {}
        for verdict in verdicts:
            for mod in verdict.modifications:
                by_target[mod.target] = mod
        return list(by_target.values())

    @staticmethod
    def _build_modified_verdict(
        verdicts: list[Verdict],
    ) -> Verdict | None:
        all_mods = BaseCompositionStrategy._collect_all_modifications(
            verdicts
        )
        if not all_mods:
            return None

        reasons = [
            v.reasoning
            for v in verdicts
            if v.decision == Decision.MODIFY
            and v.reasoning
        ]

        return Verdict(
            decision=Decision.MODIFY,
            reasoning=(
                " + ".join(reasons)
                if reasons
                else None
            ),
            modifications=all_mods,
        )
