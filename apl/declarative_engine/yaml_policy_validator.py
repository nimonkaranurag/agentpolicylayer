from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args, get_type_hints

import yaml

from apl.types import Decision, Escalation, EventType, Modification

from .condition_evaluator import ConditionEvaluator


def _literal_values(dataclass_type: type, field_name: str) -> frozenset[str]:
    """Read the allowed values of a ``Literal[...]`` field straight from the domain
    type, so the validator can never drift from ``types.py``.
    """
    field_type = get_type_hints(dataclass_type)[field_name]
    return frozenset(get_args(field_type))


# Single source of truth: derived from the domain types, never hand-listed.
_KNOWN_OPERATORS: frozenset[str] = ConditionEvaluator().known_operators
_MODIFICATION_TARGETS: frozenset[str] = _literal_values(Modification, "target")
_MODIFICATION_OPERATIONS: frozenset[str] = _literal_values(Modification, "operation")
_ESCALATION_TYPES: frozenset[str] = _literal_values(Escalation, "type")

# Operators whose argument is itself one or more nested conditions.
_LIST_OF_CONDITIONS_OPERATORS: frozenset[str] = frozenset({"any", "all"})
_SINGLE_CONDITION_OPERATORS: frozenset[str] = frozenset({"not"})


class YamlPolicyValidator:
    """
    Static validation for declarative YAML policies.

    The goal is that ``apl validate`` catches everything that would otherwise
    crash (``KeyError``/``re.error``) or silently under-enforce at evaluation
    time: unknown operators, invalid regexes, and malformed
    ``modification``/``escalation`` blocks.
    """

    def __init__(self) -> None:
        self._valid_event_type_values: frozenset[str] = frozenset(
            event_type.value for event_type in EventType
        )
        self._valid_decision_values: frozenset[str] = frozenset(
            decision.value for decision in Decision
        )

    def validate_file(self, path: Path | str) -> list[str]:
        resolved_path: Path = Path(path)
        errors: list[str] = []

        raw_data: dict[str, Any] | None = self._try_parse_yaml(resolved_path, errors)
        if raw_data is None:
            return errors

        if not self._validate_root_structure(raw_data, errors):
            return errors

        self._validate_policy_entries(raw_data.get("policies", []), errors)
        return errors

    @staticmethod
    def _try_parse_yaml(path: Path, errors: list[str]) -> dict[str, Any] | None:
        try:
            with open(path) as file_handle:
                data: Any = yaml.safe_load(file_handle)
        except yaml.YAMLError as parse_error:
            errors.append(f"YAML parse error: {parse_error}")
            return None

        if not isinstance(data, dict):
            errors.append("Root must be a mapping")
            return None

        return data

    @staticmethod
    def _validate_root_structure(data: dict[str, Any], errors: list[str]) -> bool:
        if "name" not in data:
            errors.append("Missing required field: name")

        if "policies" not in data:
            errors.append("Missing required field: policies")
            return False

        if not isinstance(data.get("policies"), list):
            errors.append("'policies' must be a list")
            return False

        return True

    def _validate_policy_entries(
        self,
        policies: list[Any],
        errors: list[str],
    ) -> None:
        for index, policy in enumerate(policies):
            error_prefix: str = f"policies[{index}]"
            self._validate_single_policy(policy, error_prefix, errors)

    def _validate_single_policy(
        self,
        policy: Any,
        error_prefix: str,
        errors: list[str],
    ) -> None:
        if not isinstance(policy, dict):
            errors.append(f"{error_prefix}: must be a mapping")
            return

        if "name" not in policy:
            errors.append(f"{error_prefix}: Missing required field 'name'")

        self._validate_events_field(policy, error_prefix, errors)
        self._validate_rules_field(policy, error_prefix, errors)

    def _validate_events_field(
        self,
        policy: dict[str, Any],
        error_prefix: str,
        errors: list[str],
    ) -> None:
        if "events" not in policy:
            errors.append(f"{error_prefix}: Missing required field 'events'")
            return

        if not isinstance(policy.get("events"), list):
            return

        for event_index, event_value in enumerate(policy["events"]):
            if event_value not in self._valid_event_type_values:
                errors.append(
                    f"{error_prefix}.events[{event_index}]: "
                    f"Invalid event type '{event_value}'"
                )

    def _validate_rules_field(
        self,
        policy: dict[str, Any],
        error_prefix: str,
        errors: list[str],
    ) -> None:
        if "rules" not in policy:
            errors.append(f"{error_prefix}: Missing required field 'rules'")
            return

        if not isinstance(policy.get("rules"), list):
            return

        for rule_index, rule in enumerate(policy["rules"]):
            rule_prefix: str = f"{error_prefix}.rules[{rule_index}]"
            self._validate_single_rule(rule, rule_prefix, errors)

    def _validate_single_rule(
        self,
        rule: Any,
        rule_prefix: str,
        errors: list[str],
    ) -> None:
        if not isinstance(rule, dict):
            errors.append(f"{rule_prefix}: must be a mapping")
            return

        if "when" not in rule:
            errors.append(f"{rule_prefix}: Missing required field 'when'")
        elif not isinstance(rule["when"], dict):
            errors.append(f"{rule_prefix}.when: must be a mapping")
        else:
            self._validate_when_clause(rule["when"], f"{rule_prefix}.when", errors)

        if "then" not in rule:
            errors.append(f"{rule_prefix}: Missing required field 'then'")
        elif not isinstance(rule["then"], dict):
            errors.append(f"{rule_prefix}.then: must be a mapping")
        else:
            self._validate_then_clause(rule["then"], f"{rule_prefix}.then", errors)

    def _validate_when_clause(
        self,
        when_clause: dict[str, Any],
        prefix: str,
        errors: list[str],
    ) -> None:
        for dot_path, condition in when_clause.items():
            self._validate_condition(condition, f"{prefix}.{dot_path}", errors)

    def _validate_condition(
        self,
        condition: Any,
        prefix: str,
        errors: list[str],
    ) -> None:
        # A non-dict condition is a literal equality check — always valid shape.
        if not isinstance(condition, dict):
            return

        if not condition:
            errors.append(f"{prefix}: empty condition mapping")
            return

        for operator_name, operator_argument in condition.items():
            if operator_name not in _KNOWN_OPERATORS:
                errors.append(f"{prefix}: unknown condition operator '{operator_name}'")
                continue

            if operator_name == "matches":
                self._validate_regex(operator_argument, f"{prefix}.matches", errors)
            elif operator_name in _LIST_OF_CONDITIONS_OPERATORS:
                self._validate_condition_list(
                    operator_argument, f"{prefix}.{operator_name}", errors
                )
            elif operator_name in _SINGLE_CONDITION_OPERATORS:
                self._validate_condition(
                    operator_argument, f"{prefix}.{operator_name}", errors
                )

    def _validate_condition_list(
        self,
        conditions: Any,
        prefix: str,
        errors: list[str],
    ) -> None:
        if not isinstance(conditions, list):
            errors.append(f"{prefix}: must be a list of conditions")
            return
        for index, condition in enumerate(conditions):
            self._validate_condition(condition, f"{prefix}[{index}]", errors)

    @staticmethod
    def _validate_regex(pattern: Any, prefix: str, errors: list[str]) -> None:
        if not isinstance(pattern, str):
            errors.append(f"{prefix}: regex pattern must be a string")
            return
        try:
            re.compile(pattern)
        except re.error as compile_error:
            errors.append(f"{prefix}: invalid regex pattern: {compile_error}")

    def _validate_then_clause(
        self,
        then_clause: dict[str, Any],
        prefix: str,
        errors: list[str],
    ) -> None:
        decision_value: str | None = then_clause.get("decision")
        if decision_value and decision_value not in self._valid_decision_values:
            errors.append(f"{prefix}.decision: Invalid decision '{decision_value}'")

        if "modification" in then_clause:
            self._validate_modification(
                then_clause["modification"], f"{prefix}.modification", errors
            )

        if "escalation" in then_clause:
            self._validate_escalation(
                then_clause["escalation"], f"{prefix}.escalation", errors
            )

    @staticmethod
    def _validate_modification(
        modification: Any,
        prefix: str,
        errors: list[str],
    ) -> None:
        if not isinstance(modification, dict):
            errors.append(f"{prefix}: must be a mapping")
            return

        # target/operation/value are read with [] at load time -> required.
        for required_field in ("target", "operation", "value"):
            if required_field not in modification:
                errors.append(f"{prefix}: missing required field '{required_field}'")

        target = modification.get("target")
        if target is not None and target not in _MODIFICATION_TARGETS:
            errors.append(f"{prefix}.target: invalid target '{target}'")

        operation = modification.get("operation")
        if operation is not None and operation not in _MODIFICATION_OPERATIONS:
            errors.append(f"{prefix}.operation: invalid operation '{operation}'")

    @staticmethod
    def _validate_escalation(
        escalation: Any,
        prefix: str,
        errors: list[str],
    ) -> None:
        if not isinstance(escalation, dict):
            errors.append(f"{prefix}: must be a mapping")
            return

        # type is read with [] at load time -> required.
        if "type" not in escalation:
            errors.append(f"{prefix}: missing required field 'type'")
        elif escalation["type"] not in _ESCALATION_TYPES:
            errors.append(
                f"{prefix}.type: invalid escalation type '{escalation['type']}'"
            )

        options = escalation.get("options")
        if options is not None and not isinstance(options, list):
            errors.append(f"{prefix}.options: must be a list")
