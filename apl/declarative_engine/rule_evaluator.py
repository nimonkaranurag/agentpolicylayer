from __future__ import annotations

from typing import Any

from apl.types import (
    Decision,
    Escalation,
    Modification,
    PolicyEvent,
    Verdict,
)

from .condition_evaluator import ConditionEvaluator
from .object_traversal import (
    get_nested_value_by_dot_path,
)
from .schema import YAMLRule
from .template_renderer import TemplateRenderer


class RuleEvaluator:

    def __init__(self) -> None:
        self._condition_evaluator = (
            ConditionEvaluator()
        )
        self._template_renderer = TemplateRenderer()

    def evaluate_rule_against_event(
        self,
        rule: YAMLRule,
        event: PolicyEvent,
    ) -> Verdict | None:
        if not self._all_conditions_match(
            rule.when, event
        ):
            return None

        return self._build_verdict_from_then_clause(
            rule.then, event
        )

    def _all_conditions_match(
        self,
        when_clause: dict[str, Any],
        event: PolicyEvent,
    ) -> bool:
        for dot_path, condition in when_clause.items():
            actual_value = (
                get_nested_value_by_dot_path(
                    event, dot_path
                )
            )
            if not self._condition_evaluator.evaluate(
                actual_value, condition
            ):
                return False
        return True

    def _build_verdict_from_then_clause(
        self,
        then_clause: dict[str, Any],
        event: PolicyEvent,
    ) -> Verdict:
        decision = Decision(
            then_clause.get("decision", "allow")
        )
        raw_reasoning = then_clause.get(
            "reasoning", ""
        )
        rendered_reasoning = (
            self._template_renderer.render(
                raw_reasoning, event
            )
        )

        modifications = []
        if "modification" in then_clause:
            modifications.append(
                self._build_modification(
                    then_clause["modification"], event
                )
            )

        escalation = None
        if "escalation" in then_clause:
            escalation = self._build_escalation(
                then_clause["escalation"], event
            )

        return Verdict(
            decision=decision,
            confidence=then_clause.get(
                "confidence", 1.0
            ),
            reasoning=rendered_reasoning or None,
            modifications=modifications,
            escalation=escalation,
        )

    def _build_modification(
        self,
        modification_data: dict[str, Any],
        event: PolicyEvent,
    ) -> Modification:
        raw_value = modification_data["value"]
        resolved_value = (
            self._template_renderer.render(
                str(raw_value), event
            )
            if isinstance(raw_value, str)
            else raw_value
        )

        return Modification(
            target=modification_data["target"],
            operation=modification_data["operation"],
            value=resolved_value,
            path=modification_data.get("path"),
        )

    def _build_escalation(
        self,
        escalation_data: dict[str, Any],
        event: PolicyEvent,
    ) -> Escalation:
        raw_prompt = escalation_data.get("prompt", "")
        rendered_prompt = (
            self._template_renderer.render(
                raw_prompt, event
            )
        )

        return Escalation(
            type=escalation_data["type"],
            prompt=rendered_prompt or None,
            fallback_action=escalation_data.get(
                "fallback_action"
            ),
            timeout_ms=escalation_data.get(
                "timeout_ms"
            ),
            options=escalation_data.get("options"),
        )
