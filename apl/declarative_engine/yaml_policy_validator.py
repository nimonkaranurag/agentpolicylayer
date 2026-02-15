from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from apl.types import Decision, EventType


class YamlPolicyValidator:

    def __init__(self) -> None:
        self._valid_event_type_values: frozenset[str] = (
            frozenset(
                event_type.value for event_type in EventType
            )
        )
        self._valid_decision_values: frozenset[str] = (
            frozenset(
                decision.value for decision in Decision
            )
        )

    def validate_file(self, path: Path | str) -> list[str]:
        resolved_path: Path = Path(path)
        errors: list[str] = []

        raw_data: dict[str, Any] | None = (
            self._try_parse_yaml(resolved_path, errors)
        )
        if raw_data is None:
            return errors

        if not self._validate_root_structure(
            raw_data, errors
        ):
            return errors

        self._validate_policy_entries(
            raw_data.get("policies", []), errors
        )
        return errors

    @staticmethod
    def _try_parse_yaml(
        path: Path, errors: list[str]
    ) -> dict[str, Any] | None:
        try:
            with open(path) as file_handle:
                data: Any = yaml.safe_load(file_handle)
        except yaml.YAMLError as parse_error:
            errors.append(
                f"YAML parse error: {parse_error}"
            )
            return None

        if not isinstance(data, dict):
            errors.append("Root must be a mapping")
            return None

        return data

    @staticmethod
    def _validate_root_structure(
        data: dict[str, Any], errors: list[str]
    ) -> bool:
        if "name" not in data:
            errors.append("Missing required field: name")

        if "policies" not in data:
            errors.append(
                "Missing required field: policies"
            )
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
            self._validate_single_policy(
                policy, error_prefix, errors
            )

    def _validate_single_policy(
        self,
        policy: dict[str, Any],
        error_prefix: str,
        errors: list[str],
    ) -> None:
        if "name" not in policy:
            errors.append(
                f"{error_prefix}: Missing required field 'name'"
            )

        self._validate_events_field(
            policy, error_prefix, errors
        )
        self._validate_rules_field(
            policy, error_prefix, errors
        )

    def _validate_events_field(
        self,
        policy: dict[str, Any],
        error_prefix: str,
        errors: list[str],
    ) -> None:
        if "events" not in policy:
            errors.append(
                f"{error_prefix}: Missing required field 'events'"
            )
            return

        if not isinstance(policy.get("events"), list):
            return

        for event_index, event_value in enumerate(
            policy["events"]
        ):
            if (
                event_value
                not in self._valid_event_type_values
            ):
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
            errors.append(
                f"{error_prefix}: Missing required field 'rules'"
            )
            return

        if not isinstance(policy.get("rules"), list):
            return

        for rule_index, rule in enumerate(policy["rules"]):
            rule_prefix: str = (
                f"{error_prefix}.rules[{rule_index}]"
            )
            self._validate_single_rule(
                rule, rule_prefix, errors
            )

    def _validate_single_rule(
        self,
        rule: dict[str, Any],
        rule_prefix: str,
        errors: list[str],
    ) -> None:
        if "when" not in rule:
            errors.append(
                f"{rule_prefix}: Missing required field 'when'"
            )

        if "then" not in rule:
            errors.append(
                f"{rule_prefix}: Missing required field 'then'"
            )
        elif isinstance(rule.get("then"), dict):
            decision_value: str | None = rule["then"].get(
                "decision"
            )
            if (
                decision_value
                and decision_value
                not in self._valid_decision_values
            ):
                errors.append(
                    f"{rule_prefix}.then.decision: "
                    f"Invalid decision '{decision_value}'"
                )
