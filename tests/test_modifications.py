from __future__ import annotations

import pytest

from apl.instrumentation.events import get_event
from apl.instrumentation.lifecycle.context import LifecycleContext
from apl.layer.decorator_evaluator import PolicyDecoratorFactory
from apl.layer.exceptions import PolicyDenied, PolicyEscalation
from apl.modifications import (
    DEFAULT_REDACTION,
    UnsupportedModificationTarget,
    apply_modifications,
    apply_operation,
)
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

    def test_modification_target_unknown_to_event_fails_closed(self):
        # A tool event has no "output" slot. A demanded modification that can't be
        # applied must fail closed (raise) — silently skipping it lets the action
        # proceed unmodified, the exact fail-open this product must not have.
        ctx = LifecycleContext(tool_args={"q": "x"}, response_text="")
        with pytest.raises(UnsupportedModificationTarget):
            get_event("tool.pre_invoke").apply_verdict_modifications(
                Verdict.modify(target="output", operation="replace", value="zzz"),
                ctx,
            )


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
        _, kwargs = PolicyDecoratorFactory._enforce_verdict(
            Verdict.modify(target="tool_args", operation="append", value={"extra": 1}),
            (),
            {"tool_args": {"q": "x"}},
        )
        assert kwargs["tool_args"] == {"q": "x", "extra": 1}

    def test_tool_args_replace_still_works(self):
        _, kwargs = PolicyDecoratorFactory._enforce_verdict(
            Verdict.modify(target="tool_args", operation="replace", value={"q": "y"}),
            (),
            {"tool_args": {"q": "x"}},
        )
        assert kwargs["tool_args"] == {"q": "y"}

    def test_tool_args_modify_written_back_to_positional_slot(self):
        # The README's own call style passes tool_args positionally:
        #   await call_tool("delete_record", {"id": 42})
        # The modified value must go back to args[1], not a tool_args= kwarg, or the
        # wrapped call raises "multiple values for argument 'tool_args'".
        args, kwargs = PolicyDecoratorFactory._enforce_verdict(
            Verdict.modify(target="tool_args", operation="append", value={"safe": 1}),
            ("delete_record", {"id": 42}),
            {},
        )
        assert args == ("delete_record", {"id": 42, "safe": 1})
        assert "tool_args" not in kwargs

    def test_non_tool_args_target_raises(self):
        # The decorator runs before the call: only inputs (tool_args) can be modified.
        with pytest.raises(UnsupportedModificationTarget):
            PolicyDecoratorFactory._enforce_verdict(
                Verdict.modify(target="output", operation="replace", value="z"),
                (),
                {},
            )

    def test_deny_raises_policy_denied(self):
        with pytest.raises(PolicyDenied):
            PolicyDecoratorFactory._enforce_verdict(Verdict.deny("nope"), (), {})

    def test_escalate_raises_policy_escalation(self):
        with pytest.raises(PolicyEscalation):
            PolicyDecoratorFactory._enforce_verdict(
                Verdict.escalate(type="human_review"), (), {}
            )

    def test_allow_is_a_noop(self):
        args, kwargs = PolicyDecoratorFactory._enforce_verdict(Verdict.allow(), (), {})
        assert args == ()
        assert kwargs == {}

    def test_decision_enum_unchanged(self):
        # Sanity: dispatcher tests rely on the canonical Decision values.
        assert Decision.MODIFY.value == "modify"


class TestSharedApplyModifications:
    # The single applier the three enforcement points route through: it must fail
    # closed on a target the point can't apply (not silently skip), and honour
    # operation order.

    def test_unsupported_target_fails_closed(self):
        with pytest.raises(UnsupportedModificationTarget):
            apply_modifications([_mod("replace", "x", target="output")], lambda t: None)

    def test_modifications_apply_in_order(self):
        box = {"v": "hi"}

        def resolve(target):
            if target != "output":
                return None
            return (lambda: box["v"], lambda value: box.__setitem__("v", value))

        apply_modifications(
            [
                _mod("append", " there", target="output"),
                _mod("append", "!", target="output"),
            ],
            resolve,
        )
        assert box["v"] == "hi there!"
