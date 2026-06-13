from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from apl.server import PolicyServer
from apl.types import Decision, PolicyEvent, Verdict

from .rule_evaluator import RuleEvaluator
from .schema import (
    YAMLManifest,
    YAMLPolicyDefinition,
    YAMLRule,
)


class YamlPolicyLoader:
    def __init__(self) -> None:
        self._rule_evaluator: RuleEvaluator = RuleEvaluator()

    def load_from_file(self, path: Path | str) -> PolicyServer:
        resolved_path: Path = Path(path)
        raw_data: dict[str, Any] = self._read_yaml_file(resolved_path)
        manifest: YAMLManifest = self._parse_manifest_from_raw_data(raw_data)

        server: PolicyServer = PolicyServer(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
        )

        for policy_definition in manifest.policies:
            self._register_policy_on_server(server, policy_definition)

        return server

    @staticmethod
    def _read_yaml_file(path: Path) -> dict[str, Any]:
        with open(path) as file_handle:
            return yaml.safe_load(file_handle)

    @staticmethod
    def _parse_manifest_from_raw_data(
        data: dict[str, Any],
    ) -> YAMLManifest:
        if "name" not in data:
            raise ValueError("Missing required field: name")

        parsed_policies: list[YAMLPolicyDefinition] = []

        for raw_policy in data.get("policies", []):
            parsed_rules: list[YAMLRule] = [
                YAMLRule(
                    when=raw_rule.get("when", {}),
                    then=raw_rule.get("then", {}),
                )
                for raw_rule in raw_policy.get("rules", [])
            ]

            parsed_policies.append(
                YAMLPolicyDefinition(
                    name=raw_policy["name"],
                    events=raw_policy.get("events", []),
                    rules=parsed_rules,
                    description=raw_policy.get("description"),
                    version=raw_policy.get("version", "1.0.0"),
                    blocking=raw_policy.get("blocking", True),
                    timeout_ms=raw_policy.get("timeout_ms", 1000),
                    default_decision=raw_policy.get("default_decision"),
                )
            )

        return YAMLManifest(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description"),
            policies=parsed_policies,
        )

    def _register_policy_on_server(
        self,
        server: PolicyServer,
        policy_definition: YAMLPolicyDefinition,
    ) -> None:
        rule_evaluator: RuleEvaluator = self._rule_evaluator
        captured_rules: list[YAMLRule] = policy_definition.rules
        no_match_verdict = self._no_match_verdict(policy_definition)

        async def yaml_policy_handler(
            event: PolicyEvent,
        ) -> Verdict:
            for rule in captured_rules:
                verdict: Verdict | None = rule_evaluator.evaluate_rule_against_event(
                    rule, event
                )
                if verdict is not None:
                    return verdict
            return no_match_verdict

        decorator = server.policy(
            name=policy_definition.name,
            events=policy_definition.events,
            version=policy_definition.version,
            blocking=policy_definition.blocking,
            timeout_ms=policy_definition.timeout_ms,
            description=policy_definition.description,
        )
        decorator(yaml_policy_handler)

    @staticmethod
    def _no_match_verdict(policy_definition: YAMLPolicyDefinition) -> Verdict:
        """
        The verdict a declarative policy returns when no rule matched.

        Default is an OBSERVE with a trace (abstain — neutral under composition),
        not a bare ALLOW: a positive ALLOW would out-vote a deny under
        allow_overrides/weighted, so a detection policy that simply didn't fire
        shouldn't cast an approve vote. A policy can opt into ``default_decision:
        deny`` (a default-deny allowlist) or ``allow``.
        """
        name = policy_definition.name
        default = policy_definition.default_decision
        trace = {"policy": name, "matched": False}

        if default is None or default == Decision.OBSERVE.value:
            return Verdict.observe(
                reasoning=f"No rule matched in policy {name!r}", trace=trace
            )
        decision = Decision(default)
        if decision is Decision.DENY:
            return Verdict.deny(
                reasoning=f"No rule matched in policy {name!r} (default_decision=deny)"
            )
        if decision is Decision.ALLOW:
            return Verdict.allow(
                reasoning=f"No rule matched in policy {name!r} (default_decision=allow)"
            )
        # MODIFY/ESCALATE can't be synthesised without a payload, so treat any
        # other configured default as an abstaining OBSERVE rather than guessing.
        return Verdict.observe(
            reasoning=f"No rule matched in policy {name!r}", trace=trace
        )
