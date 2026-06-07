from __future__ import annotations

import pytest

from apl.instrumentation.events import get_event
from apl.instrumentation.lifecycle.context import LifecycleContext
from apl.layer.decorator_evaluator import PolicyDecoratorFactory
from apl.layer.exceptions import PolicyDenied, PolicyEscalation
from apl.modifications import DEFAULT_REDACTION, apply_operation
from apl.server.policy_registry import PolicyRegistry
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Modification,
    Verdict,
)


def _mod(operation, value=None, *, target="output", path=None) -> Modification:
    return Modification(
        target=target,
        operation=operation,
        value=value,
        path=path,
    )


class TestApplyOperationReplace:
    def test_replace_returns_value(self):
        assert apply_operation("hello", _mod("replace", "world")) == "world"

    def test_replace_ignores_path(self):
        # replace is wholesale: path is not consulted, the whole value is swapped.
        result = apply_operation({"a": 1}, _mod("replace", {"b": 2}, path="$.a"))
        assert result == {"b": 2}


class TestApplyOperationAppendPrepend:
    def test_append_strings(self):
        assert apply_operation("foo", _mod("append", "bar")) == "foobar"

    def test_prepend_strings(self):
        assert apply_operation("bar", _mod("prepend", "foo")) == "foobar"

    def test_append_to_none_yields_value(self):
        assert apply_operation(None, _mod("append", "bar")) == "bar"

    def test_append_lists(self):
        assert apply_operation([1, 2], _mod("append", [3])) == [1, 2, 3]

    def test_append_scalar_to_list(self):
        assert apply_operation([1], _mod("append", 2)) == [1, 2]

    def test_prepend_lists(self):
        assert apply_operation([2, 3], _mod("prepend", [1])) == [1, 2, 3]

    def test_append_dicts_merges(self):
        assert apply_operation({"a": 1}, _mod("append", {"b": 2})) == {"a": 1, "b": 2}

    def test_append_rejects_incompatible_types(self):
        # int has no meaningful append: fail closed rather than silently no-op.
        with pytest.raises(TypeError):
            apply_operation(5, _mod("append", 6))


class TestApplyOperationRedact:
    def test_redact_whole_defaults_to_marker(self):
        assert apply_operation("secret", _mod("redact")) == DEFAULT_REDACTION

    def test_redact_whole_with_custom_marker(self):
        assert apply_operation("secret", _mod("redact", "***")) == "***"

    def test_redact_at_path_preserves_siblings(self):
        result = apply_operation(
            {"password": "hunter2", "user": "bob"},
            _mod("redact", target="tool_args", path="$.password"),
        )
        assert result == {"password": DEFAULT_REDACTION, "user": "bob"}

    def test_redact_at_path_is_distinct_from_replace(self):
        current = {"password": "hunter2", "user": "bob"}
        redacted = apply_operation(current, _mod("redact", path="$.password"))
        replaced = apply_operation(
            current, _mod("replace", "hunter2", path="$.password")
        )
        # redact masks only the leaf; replace clobbers the whole structure.
        assert redacted == {"password": DEFAULT_REDACTION, "user": "bob"}
        assert replaced == "hunter2"
        assert redacted != replaced


class TestApplyOperationPatch:
    def test_patch_sets_nested_key(self):
        result = apply_operation({"a": {"b": 1}}, _mod("patch", 9, path="$.a.b"))
        assert result == {"a": {"b": 9}}

    def test_patch_sets_list_index(self):
        result = apply_operation(
            {"items": [1, 2, 3]}, _mod("patch", 99, path="$.items[1]")
        )
        assert result == {"items": [1, 99, 3]}

    def test_patch_can_add_leaf_key(self):
        result = apply_operation({"a": 1}, _mod("patch", 2, path="$.b"))
        assert result == {"a": 1, "b": 2}

    def test_patch_does_not_mutate_input(self):
        original = {"a": {"b": 1}}
        apply_operation(original, _mod("patch", 9, path="$.a.b"))
        assert original == {"a": {"b": 1}}

    def test_patch_without_path_fails_closed(self):
        with pytest.raises(ValueError):
            apply_operation({"a": 1}, _mod("patch", 2))

    def test_patch_missing_intermediate_key_fails_closed(self):
        with pytest.raises(KeyError):
            apply_operation({"a": 1}, _mod("patch", 2, path="$.missing.deep"))

    def test_patch_non_integer_index_fails_closed(self):
        with pytest.raises(ValueError):
            apply_operation({"items": [1]}, _mod("patch", 2, path="$.items[x]"))


class TestApplyOperationUnknown:
    def test_unknown_operation_fails_closed(self):
        with pytest.raises(ValueError):
            apply_operation("x", _mod("frobnicate", "y"))


class TestEventsApplierRoutesThroughDispatcher:
    def test_output_append_appends_instead_of_replacing(self):
        ctx = LifecycleContext(response_text="hello")
        get_event("output.pre_send").apply_verdict_modifications(
            Verdict.modify(target="output", operation="append", value=" world"),
            ctx,
        )
        assert ctx.response_text == "hello world"

    def test_tool_args_redact_at_path_preserves_siblings(self):
        ctx = LifecycleContext(tool_args={"password": "hunter2", "user": "bob"})
        get_event("tool.pre_invoke").apply_verdict_modifications(
            Verdict.modify(
                target="tool_args",
                operation="redact",
                value=None,
                path="$.password",
            ),
            ctx,
        )
        assert ctx.tool_args == {"password": DEFAULT_REDACTION, "user": "bob"}

    def test_modification_target_unknown_to_event_is_skipped(self):
        # A tool event has no "output" slot: the modification is skipped, not applied.
        ctx = LifecycleContext(tool_args={"q": "x"}, response_text="")
        get_event("tool.pre_invoke").apply_verdict_modifications(
            Verdict.modify(target="output", operation="replace", value="zzz"),
            ctx,
        )
        assert ctx.tool_args == {"q": "x"}
        assert ctx.response_text == ""


class TestServerRegistryApplierRoutesThroughDispatcher:
    def test_output_append_appends_instead_of_replacing(self, make_event):
        event = make_event(
            EventType.OUTPUT_PRE_SEND,
            payload=EventPayload(output_text="hi"),
        )
        new_event = PolicyRegistry()._apply_modification(
            event, _mod("append", " there")
        )
        assert new_event.payload.output_text == "hi there"

    def test_replace_preserves_other_fields_and_does_not_mutate(self, make_event):
        event = make_event(
            EventType.OUTPUT_PRE_SEND,
            payload=EventPayload(output_text="hi", tool_name="t"),
        )
        new_event = PolicyRegistry()._apply_modification(event, _mod("replace", "bye"))
        assert new_event.payload.output_text == "bye"
        assert new_event.payload.tool_name == "t"  # untouched field preserved
        assert event.payload.output_text == "hi"  # original not mutated
        assert new_event is not event
        assert new_event.payload is not event.payload

    def test_tool_args_patch_by_path(self, make_event):
        event = make_event(
            EventType.TOOL_PRE_INVOKE,
            payload=EventPayload(tool_args={"limit": 10, "q": "x"}),
        )
        new_event = PolicyRegistry()._apply_modification(
            event, _mod("patch", 1, target="tool_args", path="$.limit")
        )
        assert new_event.payload.tool_args == {"limit": 1, "q": "x"}


class TestDecoratorApplierRoutesThroughDispatcher:
    def test_tool_args_append_is_now_supported(self):
        keyword_args = {"tool_args": {"q": "x"}}
        PolicyDecoratorFactory._enforce_verdict(
            Verdict.modify(target="tool_args", operation="append", value={"extra": 1}),
            keyword_args,
        )
        assert keyword_args["tool_args"] == {"q": "x", "extra": 1}

    def test_tool_args_replace_still_works(self):
        keyword_args = {"tool_args": {"q": "x"}}
        PolicyDecoratorFactory._enforce_verdict(
            Verdict.modify(target="tool_args", operation="replace", value={"q": "y"}),
            keyword_args,
        )
        assert keyword_args["tool_args"] == {"q": "y"}

    def test_non_tool_args_target_raises(self):
        # The decorator runs before the call: only inputs (tool_args) can be modified.
        with pytest.raises(NotImplementedError):
            PolicyDecoratorFactory._enforce_verdict(
                Verdict.modify(target="output", operation="replace", value="z"),
                {},
            )

    def test_deny_raises_policy_denied(self):
        with pytest.raises(PolicyDenied):
            PolicyDecoratorFactory._enforce_verdict(Verdict.deny("nope"), {})

    def test_escalate_raises_policy_escalation(self):
        with pytest.raises(PolicyEscalation):
            PolicyDecoratorFactory._enforce_verdict(
                Verdict.escalate(type="human_review"), {}
            )

    def test_allow_is_a_noop(self):
        keyword_args: dict = {}
        PolicyDecoratorFactory._enforce_verdict(Verdict.allow(), keyword_args)
        assert keyword_args == {}

    def test_decision_enum_unchanged(self):
        # Sanity: dispatcher tests rely on the canonical Decision values.
        assert Decision.MODIFY.value == "modify"
