from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apl.declarative_engine.condition_evaluator import ConditionEvaluator
from apl.declarative_engine.object_traversal import get_nested_value_by_dot_path
from apl.declarative_engine.rule_evaluator import RuleEvaluator
from apl.declarative_engine.schema import YAMLManifest, YAMLPolicyDefinition, YAMLRule
from apl.declarative_engine.template_renderer import TemplateRenderer
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    SessionMetadata,
)


class TestConditionEvaluator:

    def setup_method(self):
        self.evaluator = ConditionEvaluator()

    def test_equals_direct_value(self):
        assert self.evaluator.evaluate("hello", "hello") is True
        assert self.evaluator.evaluate("hello", "world") is False

    def test_equals_operator(self):
        assert self.evaluator.evaluate("a", {"equals": "a"}) is True
        assert self.evaluator.evaluate("a", {"equals": "b"}) is False

    def test_matches_regex(self):
        assert self.evaluator.evaluate("foo123", {"matches": r"foo\d+"}) is True
        assert self.evaluator.evaluate("bar", {"matches": r"foo\d+"}) is False

    def test_matches_case_insensitive(self):
        assert self.evaluator.evaluate("Hello", {"matches": "hello"}) is True

    def test_matches_none_value(self):
        assert self.evaluator.evaluate(None, {"matches": "anything"}) is False

    def test_contains_string(self):
        assert self.evaluator.evaluate("hello world", {"contains": "world"}) is True
        assert self.evaluator.evaluate("hello", {"contains": "xyz"}) is False

    def test_contains_list(self):
        assert self.evaluator.evaluate([1, 2, 3], {"contains": 2}) is True
        assert self.evaluator.evaluate([1, 2, 3], {"contains": 5}) is False

    def test_contains_none(self):
        assert self.evaluator.evaluate(None, {"contains": "x"}) is False

    def test_gt(self):
        assert self.evaluator.evaluate(10, {"gt": 5}) is True
        assert self.evaluator.evaluate(5, {"gt": 5}) is False
        assert self.evaluator.evaluate(None, {"gt": 5}) is False

    def test_gte(self):
        assert self.evaluator.evaluate(5, {"gte": 5}) is True
        assert self.evaluator.evaluate(4, {"gte": 5}) is False

    def test_lt(self):
        assert self.evaluator.evaluate(3, {"lt": 5}) is True
        assert self.evaluator.evaluate(5, {"lt": 5}) is False

    def test_lte(self):
        assert self.evaluator.evaluate(5, {"lte": 5}) is True
        assert self.evaluator.evaluate(6, {"lte": 5}) is False

    def test_in_membership(self):
        assert self.evaluator.evaluate("a", {"in": ["a", "b", "c"]}) is True
        assert self.evaluator.evaluate("z", {"in": ["a", "b", "c"]}) is False

    def test_not_negation(self):
        assert self.evaluator.evaluate("a", {"not": "b"}) is True
        assert self.evaluator.evaluate("a", {"not": "a"}) is False

    def test_any_of(self):
        assert self.evaluator.evaluate("b", {"any": ["a", "b", "c"]}) is True
        assert self.evaluator.evaluate("z", {"any": ["a", "b"]}) is False

    def test_all_of(self):
        assert self.evaluator.evaluate(10, {"all": [{"gt": 5}, {"lt": 15}]}) is True
        assert self.evaluator.evaluate(3, {"all": [{"gt": 5}, {"lt": 15}]}) is False

    def test_none_condition(self):
        assert self.evaluator.evaluate(None, None) is True
        assert self.evaluator.evaluate("x", None) is False

    def test_custom_condition_registration(self):
        self.evaluator.register_condition(
            "starts_with",
            lambda val, prefix: isinstance(val, str) and val.startswith(prefix),
        )
        assert self.evaluator.evaluate("foobar", {"starts_with": "foo"}) is True
        assert self.evaluator.evaluate("bar", {"starts_with": "foo"}) is False


class TestObjectTraversal:

    def test_dict_traversal(self):
        obj = {"a": {"b": {"c": 42}}}
        assert get_nested_value_by_dot_path(obj, "a.b.c") == 42

    def test_object_traversal(self):
        class Inner:
            value = 99

        class Outer:
            inner = Inner()

        assert get_nested_value_by_dot_path(Outer(), "inner.value") == 99

    def test_mixed_traversal(self, sample_event: PolicyEvent):
        result = get_nested_value_by_dot_path(sample_event, "payload.output_text")
        assert result == "Hello, world!"

    def test_metadata_traversal(self, sample_event: PolicyEvent):
        result = get_nested_value_by_dot_path(sample_event, "metadata.user_region")
        assert result == "EU"

    def test_missing_path_returns_none(self):
        assert get_nested_value_by_dot_path({"a": 1}, "a.b.c") is None

    def test_none_root_returns_none(self):
        assert get_nested_value_by_dot_path(None, "anything") is None

    def test_single_level(self):
        assert get_nested_value_by_dot_path({"x": 5}, "x") == 5


class TestTemplateRenderer:

    def setup_method(self):
        self.renderer = TemplateRenderer()

    def test_no_template_passthrough(self):
        assert self.renderer.render("plain text", None) == "plain text"

    def test_variable_substitution(self, sample_event: PolicyEvent):
        result = self.renderer.render(
            "Output was: {{payload.output_text}}",
            sample_event,
        )
        assert result == "Output was: Hello, world!"

    def test_metadata_substitution(self, sample_event: PolicyEvent):
        result = self.renderer.render("User: {{metadata.user_id}}", sample_event)
        assert result == "User: user-42"

    def test_missing_variable_renders_empty(self, sample_event: PolicyEvent):
        result = self.renderer.render("Missing: {{payload.nonexistent}}", sample_event)
        assert result == "Missing: "

    def test_multiple_variables(self, sample_event: PolicyEvent):
        result = self.renderer.render(
            "{{metadata.user_id}} sent {{payload.output_text}}",
            sample_event,
        )
        assert result == "user-42 sent Hello, world!"


class TestRuleEvaluator:

    def setup_method(self):
        self.evaluator = RuleEvaluator()

    def _make_event(self, output_text="test", user_region="EU"):
        return PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType.OUTPUT_PRE_SEND,
            timestamp=datetime.now(timezone.utc),
            messages=[],
            payload=EventPayload(output_text=output_text),
            metadata=SessionMetadata(
                session_id="s1",
                user_region=user_region,
            ),
        )

    def test_matching_rule_returns_verdict(self):
        rule = YAMLRule(
            when={"payload.output_text": {"contains": "SECRET"}},
            then={"decision": "deny", "reasoning": "contains secret"},
        )
        event = self._make_event(output_text="this has SECRET data")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result is not None
        assert result.decision == Decision.DENY
        assert result.reasoning == "contains secret"

    def test_non_matching_rule_returns_none(self):
        rule = YAMLRule(
            when={"payload.output_text": {"contains": "SECRET"}},
            then={"decision": "deny", "reasoning": "blocked"},
        )
        event = self._make_event(output_text="nothing here")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result is None

    def test_template_in_reasoning(self):
        rule = YAMLRule(
            when={"metadata.user_region": "EU"},
            then={"decision": "deny", "reasoning": "Blocked for {{metadata.user_region}} users"},
        )
        event = self._make_event(user_region="EU")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result.reasoning == "Blocked for EU users"

    def test_multiple_conditions_all_must_match(self):
        rule = YAMLRule(
            when={
                "payload.output_text": {"contains": "hello"},
                "metadata.user_region": "US",
            },
            then={"decision": "allow"},
        )
        event = self._make_event(output_text="hello world", user_region="EU")
        assert self.evaluator.evaluate_rule_against_event(rule, event) is None

        event = self._make_event(output_text="hello world", user_region="US")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result is not None
        assert result.decision == Decision.ALLOW

    def test_modification_in_then(self):
        rule = YAMLRule(
            when={"payload.output_text": {"contains": "PII"}},
            then={
                "decision": "modify",
                "modification": {
                    "target": "output",
                    "operation": "replace",
                    "value": "[REDACTED]",
                },
            },
        )
        event = self._make_event(output_text="has PII here")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result.decision == Decision.MODIFY
        assert result.modification.value == "[REDACTED]"

    def test_escalation_in_then(self):
        rule = YAMLRule(
            when={"payload.output_text": {"contains": "danger"}},
            then={
                "decision": "escalate",
                "escalation": {
                    "type": "human_review",
                    "prompt": "Review: {{payload.output_text}}",
                },
            },
        )
        event = self._make_event(output_text="danger ahead")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result.decision == Decision.ESCALATE
        assert result.escalation.prompt == "Review: danger ahead"


class TestYAMLSchema:

    def test_yaml_rule_dataclass(self):
        rule = YAMLRule(when={"x": 1}, then={"decision": "allow"})
        assert rule.when == {"x": 1}

    def test_yaml_policy_definition(self):
        p = YAMLPolicyDefinition(
            name="test",
            events=["output.pre_send"],
            rules=[YAMLRule(when={}, then={"decision": "allow"})],
        )
        assert p.version == "1.0.0"
        assert p.blocking is True

    def test_yaml_manifest(self):
        m = YAMLManifest(name="server", version="1.0", policies=[])
        assert m.description is None
