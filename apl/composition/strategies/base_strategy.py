from __future__ import annotations

from typing import Protocol

from apl.types import CompositionConfig, Decision, Modification, Verdict


class CompositionStrategy(Protocol):
    def compose(self, verdicts: list[Verdict]) -> Verdict: ...


class BaseCompositionStrategy:
    """
    Shared helpers for the built-in composition strategies.

    The active :class:`CompositionConfig` is injected at construction so a strategy can
    read the fields that tune it — ``weights`` for weighted voting, ``priority`` for
    first-applicable ordering. Strategies that need neither simply ignore
    ``self._config``.
    """

    def __init__(self, config: CompositionConfig | None = None) -> None:
        self._config: CompositionConfig = config or CompositionConfig()

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
            return Verdict.allow(reasoning=fallback_reasoning)
        return None

    @staticmethod
    def _collect_all_modifications(
        verdicts: list[Verdict],
    ) -> list[Modification]:
        """
        Collect, in order, every modification a ``MODIFY`` verdict demands.

        Two rules, both load-bearing for enforcement:

        - **Only ``MODIFY`` verdicts contribute.** A modification riding on a
          ``DENY``/``ESCALATE``/``ALLOW`` verdict is not a request to apply it, so
          harvesting it into the composed ``MODIFY`` would apply a transform the
          composing decision never authorised.
        - **Modifications are an ordered list, not collapsed per target.** When two
          policies both touch ``output`` — the canonical *redact PII* + *append a
          disclaimer* case — both must survive and apply in sequence; a per-target
          ``dict`` kept only the last writer and silently dropped the redaction.
          Only an exact duplicate (same target/operation/path/value) is dropped, so
          two servers emitting the identical mod don't double-apply it.
        """
        collected: list[Modification] = []
        seen: set[tuple[str, str, str | None, str]] = set()
        for verdict in verdicts:
            if verdict.decision is not Decision.MODIFY:
                continue
            for mod in verdict.modifications:
                identity = (mod.target, mod.operation, mod.path, repr(mod.value))
                if identity in seen:
                    continue
                seen.add(identity)
                collected.append(mod)
        return collected

    @staticmethod
    def _build_modified_verdict(
        verdicts: list[Verdict],
    ) -> Verdict | None:
        all_mods = BaseCompositionStrategy._collect_all_modifications(verdicts)
        if not all_mods:
            return None

        reasons = [
            v.reasoning
            for v in verdicts
            if v.decision == Decision.MODIFY and v.reasoning
        ]

        return Verdict(
            decision=Decision.MODIFY,
            reasoning=(" + ".join(reasons) if reasons else None),
            modifications=all_mods,
        )
