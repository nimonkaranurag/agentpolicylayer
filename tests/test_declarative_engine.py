from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apl.declarative_engine import load_yaml_policy, validate_yaml_policy
from apl.declarative_engine.condition_evaluator import (
    ConditionEvaluator,
)
from apl.declarative_engine.object_traversal import (
    get_nested_value_by_dot_path,
)
from apl.declarative_engine.rule_evaluator import (
    RuleEvaluator,
)
from apl.declarative_engine.schema import (
    YAMLManifest,
    YAMLPolicyDefinition,
    YAMLRule,
)
from apl.declarative_engine.template_renderer import (
    TemplateRenderer,
)
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    PolicyEvent,
    SessionMetadata,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


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
        result = self.renderer.render(
            "Missing: {{payload.nonexistent}}",
            sample_event,
        )
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
            then={
                "decision": "deny",
                "reasoning": "contains secret",
            },
        )
        event = self._make_event(output_text="this has SECRET data")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result is not None
        assert result.decision == Decision.DENY
        assert result.reasoning == "contains secret"

    def test_non_matching_rule_returns_none(self):
        rule = YAMLRule(
            when={"payload.output_text": {"contains": "SECRET"}},
            then={
                "decision": "deny",
                "reasoning": "blocked",
            },
        )
        event = self._make_event(output_text="nothing here")
        result = self.evaluator.evaluate_rule_against_event(rule, event)
        assert result is None

    def test_template_in_reasoning(self):
        rule = YAMLRule(
            when={"metadata.user_region": "EU"},
            then={
                "decision": "deny",
                "reasoning": "Blocked for {{metadata.user_region}} users",
            },
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
        assert result.modifications[0].value == "[REDACTED]"

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


# =============================================================================
# dot-path traversal must return dict VALUES, not dict METHODS
# =============================================================================


class TestTraversalDictMethodShadowing:
    # A dict key whose name collides with a dict method (items, keys, get, ...)
    # must resolve to the stored value, never the bound method. Otherwise a YAML
    # rule referencing such a key silently never matches (silent policy bypass).

    def test_key_named_items_resolves_value(self):
        obj = {"metadata": {"custom": {"items": "secret-value"}}}
        assert (
            get_nested_value_by_dot_path(obj, "metadata.custom.items") == "secret-value"
        )

    @pytest.mark.parametrize("method_name", ["keys", "values", "get", "update", "pop"])
    def test_every_dict_method_name_is_shadowed_by_key(self, method_name):
        custom = {method_name: f"value-of-{method_name}"}
        result = get_nested_value_by_dot_path(
            {"custom": custom}, f"custom.{method_name}"
        )
        assert result == f"value-of-{method_name}"

    def test_absent_method_named_key_returns_none_not_method(self):
        # 'keys' is NOT a key here; must return None, never the bound method.
        result = get_nested_value_by_dot_path({"custom": {"x": 1}}, "custom.keys")
        assert result is None

    def test_through_real_session_metadata_custom(self):
        event = PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType.OUTPUT_PRE_SEND,
            timestamp=datetime.now(timezone.utc),
            messages=[],
            payload=EventPayload(),
            metadata=SessionMetadata(
                session_id="s1",
                custom={"items": "secret-value", "region": "EU"},
            ),
        )
        assert (
            get_nested_value_by_dot_path(event, "metadata.custom.items")
            == "secret-value"
        )
        # Sanity: a non-shadowing key still resolves.
        assert get_nested_value_by_dot_path(event, "metadata.custom.region") == "EU"


# =============================================================================
# unknown operators error; matches semantics; bad regex is loud
# =============================================================================


class TestUnknownConditionOperator:
    # A typo'd / unknown operator must raise, not silently disable the rule.

    def setup_method(self):
        self.evaluator = ConditionEvaluator()

    def test_typoed_operator_raises(self):
        with pytest.raises(ValueError, match="contians"):
            self.evaluator.evaluate("x", {"contians": "x"})  # typo of 'contains'

    def test_empty_condition_mapping_raises(self):
        with pytest.raises(ValueError):
            self.evaluator.evaluate("x", {})

    def test_known_operators_property_exposes_builtins(self):
        assert {
            "equals",
            "matches",
            "contains",
            "in",
            "not",
            "any",
            "all",
        } <= self.evaluator.known_operators

    def test_registered_custom_operator_is_known(self):
        self.evaluator.register_condition(
            "starts_with",
            lambda value, prefix: isinstance(value, str) and value.startswith(prefix),
        )
        assert "starts_with" in self.evaluator.known_operators
        assert self.evaluator.evaluate("foobar", {"starts_with": "foo"}) is True

    def test_unknown_nested_operator_in_any_raises(self):
        with pytest.raises(ValueError, match="contians"):
            self.evaluator.evaluate("x", {"any": [{"contians": "x"}]})


class TestMatchesSemantics:
    # matches = case-insensitive re.search (matches anywhere); an invalid
    # pattern fails loudly rather than silently never matching.

    def setup_method(self):
        self.evaluator = ConditionEvaluator()

    def test_matches_searches_anywhere_not_only_at_start(self):
        # re.match (the pre-fix behaviour) anchors at the start and would
        # return False here -> a detection rule silently never fires.
        assert (
            self.evaluator.evaluate("this has SECRET data", {"matches": "SECRET"})
            is True
        )

    def test_matches_is_case_insensitive(self):
        assert self.evaluator.evaluate("HELLO", {"matches": "hello"}) is True

    def test_explicit_anchors_still_work(self):
        assert self.evaluator.evaluate("foo123", {"matches": r"^foo\d+$"}) is True
        assert self.evaluator.evaluate("xfoo123", {"matches": r"^foo\d+$"}) is False

    def test_invalid_regex_raises_value_error(self):
        with pytest.raises(ValueError, match="regex"):
            self.evaluator.evaluate("anything", {"matches": "[unclosed"})

    def test_non_string_pattern_raises_value_error(self):
        with pytest.raises(ValueError, match="regex"):
            self.evaluator.evaluate("anything", {"matches": 123})


# =============================================================================
# the validator must catch what previously crashed at eval time
# =============================================================================


def _write_policy(tmp_path: Path, body: str) -> Path:
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(body)
    return policy_file


UNKNOWN_OPERATOR_POLICY = """
name: s
policies:
  - name: p
    events: [output.pre_send]
    rules:
      - when:
          payload.output_text:
            contians: SECRET
        then:
          decision: deny
"""

UNKNOWN_NESTED_OPERATOR_POLICY = """
name: s
policies:
  - name: p
    events: [output.pre_send]
    rules:
      - when:
          payload.output_text:
            any:
              - contains: ok
              - kontains: typo
        then:
          decision: deny
"""

INVALID_REGEX_POLICY = """
name: s
policies:
  - name: p
    events: [output.pre_send]
    rules:
      - when:
          payload.output_text:
            matches: "[unclosed"
        then:
          decision: deny
"""

MODIFICATION_MISSING_FIELDS_POLICY = """
name: s
policies:
  - name: p
    events: [output.pre_send]
    rules:
      - when:
          payload.output_text: anything
        then:
          decision: modify
          modification:
            value: "[REDACTED]"
"""

INVALID_MODIFICATION_POLICY = """
name: s
policies:
  - name: p
    events: [output.pre_send]
    rules:
      - when:
          payload.output_text: anything
        then:
          decision: modify
          modification:
            target: nowhere
            operation: obliterate
            value: x
"""

ESCALATION_MISSING_TYPE_POLICY = """
name: s
policies:
  - name: p
    events: [tool.pre_invoke]
    rules:
      - when:
          payload.tool_name: anything
        then:
          decision: escalate
          escalation:
            prompt: "review please"
"""

INVALID_ESCALATION_TYPE_POLICY = """
name: s
policies:
  - name: p
    events: [tool.pre_invoke]
    rules:
      - when:
          payload.tool_name: anything
        then:
          decision: escalate
          escalation:
            type: telepathy
"""

NON_MAPPING_WHEN_POLICY = """
name: s
policies:
  - name: p
    events: [output.pre_send]
    rules:
      - when: "not a mapping"
        then:
          decision: deny
"""

VALID_MOD_AND_ESCALATION_POLICY = """
name: s
policies:
  - name: redactor
    events: [output.pre_send]
    rules:
      - when:
          payload.output_text:
            contains: PII
        then:
          decision: modify
          modification:
            target: output
            operation: redact
            value: "[REDACTED]"
  - name: gate
    events: [tool.pre_invoke]
    rules:
      - when:
          payload.tool_name:
            matches: ".*delete.*"
        then:
          decision: escalate
          escalation:
            type: human_confirm
            prompt: "Confirm?"
            options: [Proceed, Cancel]
"""


class TestValidatorDeepChecks:
    def test_unknown_operator_is_reported(self, tmp_path):
        errors = validate_yaml_policy(_write_policy(tmp_path, UNKNOWN_OPERATOR_POLICY))
        assert any("contians" in e for e in errors), errors

    def test_unknown_nested_operator_is_reported(self, tmp_path):
        errors = validate_yaml_policy(
            _write_policy(tmp_path, UNKNOWN_NESTED_OPERATOR_POLICY)
        )
        assert any("kontains" in e for e in errors), errors

    def test_invalid_regex_is_reported(self, tmp_path):
        errors = validate_yaml_policy(_write_policy(tmp_path, INVALID_REGEX_POLICY))
        assert any("regex" in e.lower() for e in errors), errors

    def test_modification_missing_fields_is_reported(self, tmp_path):
        errors = validate_yaml_policy(
            _write_policy(tmp_path, MODIFICATION_MISSING_FIELDS_POLICY)
        )
        # 'target' and 'operation' are required by Modification and are read
        # with [] at load time (KeyError) -> validator must flag them.
        assert any("target" in e for e in errors), errors
        assert any("operation" in e for e in errors), errors

    def test_invalid_modification_target_and_operation_reported(self, tmp_path):
        errors = validate_yaml_policy(
            _write_policy(tmp_path, INVALID_MODIFICATION_POLICY)
        )
        assert any("nowhere" in e for e in errors), errors
        assert any("obliterate" in e for e in errors), errors

    def test_escalation_missing_type_is_reported(self, tmp_path):
        errors = validate_yaml_policy(
            _write_policy(tmp_path, ESCALATION_MISSING_TYPE_POLICY)
        )
        assert any("type" in e for e in errors), errors

    def test_invalid_escalation_type_is_reported(self, tmp_path):
        errors = validate_yaml_policy(
            _write_policy(tmp_path, INVALID_ESCALATION_TYPE_POLICY)
        )
        assert any("telepathy" in e for e in errors), errors

    def test_non_mapping_when_is_reported(self, tmp_path):
        errors = validate_yaml_policy(_write_policy(tmp_path, NON_MAPPING_WHEN_POLICY))
        assert any("when" in e for e in errors), errors

    def test_valid_policy_with_modification_and_escalation_has_no_errors(
        self, tmp_path
    ):
        errors = validate_yaml_policy(
            _write_policy(tmp_path, VALID_MOD_AND_ESCALATION_POLICY)
        )
        assert errors == []

    def test_shipped_compliance_example_validates_clean(self):
        # Regression guard: the stricter validator must not reject the valid
        # example policy that ships in the repo.
        errors = validate_yaml_policy(EXAMPLES_DIR / "compliance.yaml")
        assert errors == []


class TestDeclarativeEngineFailsClosedAtRuntime:
    # End-to-end: a typo'd operator that escapes validation must DENY at runtime
    # (via fail-closed), never silently allow.

    def test_typoed_operator_policy_denies(self, tmp_path):
        policy_file = _write_policy(tmp_path, UNKNOWN_OPERATOR_POLICY)
        server = load_yaml_policy(policy_file)
        event = PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType.OUTPUT_PRE_SEND,
            timestamp=datetime.now(timezone.utc),
            messages=[],
            payload=EventPayload(output_text="this has SECRET data"),
            metadata=SessionMetadata(session_id="s1"),
        )
        verdicts = asyncio.run(server.evaluate(event))
        assert verdicts
        assert verdicts[0].decision == Decision.DENY
