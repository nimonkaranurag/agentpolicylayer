"""
APL Declarative Policies

Load and execute policies defined in YAML format without writing Python code.

Features:
- Simple rule-based policies
- Pattern matching for tool names, content, etc.
- Built-in validators (regex, contains, equals, gt, lt)
- Template variables for dynamic messages

Example YAML policy:

    name: confirm-destructive
    version: 1.0.0
    description: Require confirmation for destructive operations

    policies:
      - name: confirm-delete
        events:
          - tool.pre_invoke
        rules:
          - when:
              payload.tool_name:
                matches: ".*delete.*"
            then:
              decision: escalate
              escalation:
                type: human_confirm
                prompt: "Confirm delete of {{payload.tool_args.path}}?"

Usage:
    from apl.declarative import load_yaml_policy

    server = load_yaml_policy("./policy.yaml")
    server.run()
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from .server import PolicyServer
from .types import (
    Decision,
    Escalation,
    EventType,
    Modification,
    PolicyEvent,
    Verdict,
)

# =============================================================================
# YAML SCHEMA
# =============================================================================


@dataclass
class YAMLRule:
    """A single rule in a YAML policy."""

    when: dict[str, Any]
    then: dict[str, Any]


@dataclass
class YAMLPolicyDef:
    """A policy definition from YAML."""

    name: str
    events: list[str]
    rules: list[YAMLRule]
    description: Optional[str] = None
    version: str = "1.0.0"
    blocking: bool = True
    timeout_ms: int = 1000


@dataclass
class YAMLManifest:
    """Complete YAML policy manifest."""

    name: str
    version: str
    policies: list[YAMLPolicyDef]
    description: Optional[str] = None


# =============================================================================
# CONDITION EVALUATORS
# =============================================================================


def evaluate_condition(value: Any, condition: Any) -> bool:
    """
    Evaluate a condition against a value.

    Supported conditions:
        - Simple value: exact match
        - {"equals": x}: exact match
        - {"matches": pattern}: regex match
        - {"contains": x}: substring/member check
        - {"gt": x}: greater than
        - {"gte": x}: greater than or equal
        - {"lt": x}: less than
        - {"lte": x}: less than or equal
        - {"in": [...]}: value in list
        - {"not": condition}: negation
        - {"any": [conditions]}: any condition matches
        - {"all": [conditions]}: all conditions match

    Args:
        value: The value to test
        condition: The condition to evaluate

    Returns:
        True if condition matches, False otherwise
    """
    if condition is None:
        return value is None

    if isinstance(condition, dict):
        # Complex condition
        if "equals" in condition:
            return value == condition["equals"]

        if "matches" in condition:
            if value is None:
                return False
            pattern = condition["matches"]
            return bool(
                re.match(pattern, str(value), re.IGNORECASE)
            )

        if "contains" in condition:
            if value is None:
                return False
            needle = condition["contains"]
            if isinstance(value, str):
                return needle in value
            if isinstance(value, (list, tuple, set)):
                return needle in value
            if isinstance(value, dict):
                return needle in value
            return False

        if "gt" in condition:
            return (
                value is not None
                and value > condition["gt"]
            )

        if "gte" in condition:
            return (
                value is not None
                and value >= condition["gte"]
            )

        if "lt" in condition:
            return (
                value is not None
                and value < condition["lt"]
            )

        if "lte" in condition:
            return (
                value is not None
                and value <= condition["lte"]
            )

        if "in" in condition:
            return value in condition["in"]

        if "not" in condition:
            return not evaluate_condition(
                value, condition["not"]
            )

        if "any" in condition:
            return any(
                evaluate_condition(value, c)
                for c in condition["any"]
            )

        if "all" in condition:
            return all(
                evaluate_condition(value, c)
                for c in condition["all"]
            )

        # Unknown condition type - treat as exact match
        return value == condition

    # Simple value - exact match
    return value == condition


def get_nested_value(obj: Any, path: str) -> Any:
    """
    Get a nested value from an object using dot notation.

    Args:
        obj: The object to traverse
        path: Dot-separated path (e.g., "payload.tool_name")

    Returns:
        The value at the path, or None if not found
    """
    parts = path.split(".")
    current = obj

    for part in parts:
        if current is None:
            return None

        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None

    return current


def interpolate_template(
    template: str, event: PolicyEvent
) -> str:
    """
    Interpolate template variables in a string.

    Supports {{path.to.value}} syntax.

    Args:
        template: String with template variables
        event: PolicyEvent to get values from

    Returns:
        Interpolated string
    """
    if "{{" not in template:
        return template

    def replace_var(match):
        path = match.group(1).strip()
        value = get_nested_value(event, path)
        return str(value) if value is not None else ""

    return re.sub(r"\{\{(.+?)\}\}", replace_var, template)


# =============================================================================
# RULE EVALUATION
# =============================================================================


def evaluate_rule(
    rule: YAMLRule, event: PolicyEvent
) -> Optional[Verdict]:
    """
    Evaluate a single rule against an event.

    Args:
        rule: The rule to evaluate
        event: The event to check

    Returns:
        Verdict if rule matches, None otherwise
    """
    # Check all conditions in "when"
    for path, condition in rule.when.items():
        value = get_nested_value(event, path)
        if not evaluate_condition(value, condition):
            return None  # Condition not met

    # All conditions met - build verdict from "then"
    then = rule.then
    decision = Decision(then.get("decision", "allow"))

    verdict = Verdict(
        decision=decision,
        confidence=then.get("confidence", 1.0),
        reasoning=interpolate_template(
            then.get("reasoning", ""), event
        )
        or None,
    )

    # Handle modification
    if "modification" in then:
        m = then["modification"]
        verdict.modification = Modification(
            target=m["target"],
            operation=m["operation"],
            value=(
                interpolate_template(str(m["value"]), event)
                if isinstance(m["value"], str)
                else m["value"]
            ),
            path=m.get("path"),
        )

    # Handle escalation
    if "escalation" in then:
        e = then["escalation"]
        verdict.escalation = Escalation(
            type=e["type"],
            prompt=interpolate_template(
                e.get("prompt", ""), event
            )
            or None,
            fallback_action=e.get("fallback_action"),
            timeout_ms=e.get("timeout_ms"),
            options=e.get("options"),
        )

    return verdict


# =============================================================================
# LOADER
# =============================================================================


def load_yaml_policy(path: Path | str) -> PolicyServer:
    """
    Load a declarative YAML policy and create a PolicyServer.

    Args:
        path: Path to the YAML file

    Returns:
        Configured PolicyServer

    Raises:
        ValueError: If the YAML is invalid
        FileNotFoundError: If the file doesn't exist

    Example:
        server = load_yaml_policy("./policies/pii.yaml")
        server.run()
    """
    path = Path(path)

    with open(path) as f:
        data = yaml.safe_load(f)

    # Parse manifest
    manifest = _parse_manifest(data)

    # Create server
    server = PolicyServer(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
    )

    # Register policies
    for policy_def in manifest.policies:
        _register_yaml_policy(server, policy_def)

    return server


def _parse_manifest(data: dict) -> YAMLManifest:
    """Parse YAML data into a manifest."""
    if "name" not in data:
        raise ValueError("Missing required field: name")

    policies = []
    for p in data.get("policies", []):
        rules = []
        for r in p.get("rules", []):
            rules.append(
                YAMLRule(
                    when=r.get("when", {}),
                    then=r.get("then", {}),
                )
            )

        policies.append(
            YAMLPolicyDef(
                name=p["name"],
                events=p.get("events", []),
                rules=rules,
                description=p.get("description"),
                version=p.get("version", "1.0.0"),
                blocking=p.get("blocking", True),
                timeout_ms=p.get("timeout_ms", 1000),
            )
        )

    return YAMLManifest(
        name=data["name"],
        version=data.get("version", "1.0.0"),
        description=data.get("description"),
        policies=policies,
    )


def _register_yaml_policy(
    server: PolicyServer, policy_def: YAMLPolicyDef
):
    """Register a YAML policy definition with the server."""

    # Create the policy handler
    async def yaml_policy_handler(
        event: PolicyEvent,
    ) -> Verdict:
        """Generated handler for YAML policy."""
        for rule in policy_def.rules:
            verdict = evaluate_rule(rule, event)
            if verdict is not None:
                return verdict

        return Verdict.allow()

    # Use the decorator to register
    decorator = server.policy(
        name=policy_def.name,
        events=policy_def.events,
        version=policy_def.version,
        blocking=policy_def.blocking,
        timeout_ms=policy_def.timeout_ms,
        description=policy_def.description,
    )

    decorator(yaml_policy_handler)


# =============================================================================
# VALIDATION
# =============================================================================


def validate_yaml_policy(path: Path | str) -> list[str]:
    """
    Validate a YAML policy file without loading it.

    Args:
        path: Path to the YAML file

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    path = Path(path)

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML parse error: {e}")
        return errors

    if not isinstance(data, dict):
        errors.append("Root must be a mapping")
        return errors

    if "name" not in data:
        errors.append("Missing required field: name")

    if "policies" not in data:
        errors.append("Missing required field: policies")
        return errors

    if not isinstance(data.get("policies"), list):
        errors.append("'policies' must be a list")
        return errors

    valid_events = {e.value for e in EventType}
    valid_decisions = {d.value for d in Decision}

    for i, policy in enumerate(data.get("policies", [])):
        prefix = f"policies[{i}]"

        if "name" not in policy:
            errors.append(
                f"{prefix}: Missing required field 'name'"
            )

        if "events" not in policy:
            errors.append(
                f"{prefix}: Missing required field 'events'"
            )
        elif isinstance(policy.get("events"), list):
            for j, event in enumerate(policy["events"]):
                if event not in valid_events:
                    errors.append(
                        f"{prefix}.events[{j}]: Invalid event type '{event}'"
                    )

        if "rules" not in policy:
            errors.append(
                f"{prefix}: Missing required field 'rules'"
            )
        elif isinstance(policy.get("rules"), list):
            for j, rule in enumerate(policy["rules"]):
                rule_prefix = f"{prefix}.rules[{j}]"

                if "when" not in rule:
                    errors.append(
                        f"{rule_prefix}: Missing required field 'when'"
                    )

                if "then" not in rule:
                    errors.append(
                        f"{rule_prefix}: Missing required field 'then'"
                    )
                elif isinstance(rule.get("then"), dict):
                    decision = rule["then"].get("decision")
                    if (
                        decision
                        and decision not in valid_decisions
                    ):
                        errors.append(
                            f"{rule_prefix}.then.decision: Invalid decision '{decision}'"
                        )

    return errors
