from __future__ import annotations

import asyncio

from apl.instrumentation.evaluation.policy_evaluator import (
    PolicyEvaluator,
)
from apl.instrumentation.events import (
    EVENT_REGISTRY,
    BaseEvent,
    RegisteredEvent,
    get_event,
)
from apl.instrumentation.execution import (
    AsyncLifecycleExecutor,
    BaseLifecycleExecutor,
    StreamingLifecycleExecutor,
    SyncLifecycleExecutor,
)
from apl.instrumentation.lifecycle.context import (
    LifecycleContext,
)
from apl.instrumentation.state import (
    InstrumentationState,
)
from apl.layer import PolicyLayer
from apl.types import (
    CompositionConfig,
    Decision,
    EventPayload,
    EventType,
    FailMode,
    Message,
    Verdict,
)


class TestEventRegistry:
    def test_one_registered_event_per_event_type(self):
        assert len(EVENT_REGISTRY) == len(EventType)
        assert set(EVENT_REGISTRY) == {e.value for e in EventType}

    def test_get_event_returns_registered_event_with_matching_type(self):
        for name in EVENT_REGISTRY:
            event = get_event(name)
            assert isinstance(event, RegisteredEvent)
            assert event.event_type.value == name

    def test_all_events_are_base_event_subclasses(self):
        for event in EVENT_REGISTRY.values():
            assert isinstance(event, BaseEvent)


def _populated_context() -> LifecycleContext:
    return LifecycleContext(
        apl_messages=[Message(role="user", content="hi")],
        model_name="gpt-4",
        response_text="answer",
        tool_name="search",
        tool_args={"q": "x"},
        tool_result={"r": 1},
        proposed_plan=["step-1"],
        source_agent="a",
        target_agent="b",
        handoff_payload={"k": "v"},
    )


# The payload each event is expected to build from a fully-populated context. This is the
# behaviour parity check for the events consolidation: it independently re-encodes the
# field mapping that used to live in 13 separate build_payload() overrides.
_EXPECTED_PAYLOADS: dict[str, EventPayload] = {
    "input.received": EventPayload(),
    "input.validated": EventPayload(),
    "llm.pre_request": EventPayload(
        llm_model="gpt-4",
        llm_prompt=[Message(role="user", content="hi")],
    ),
    "llm.post_response": EventPayload(
        llm_model="gpt-4",
        llm_response=Message(role="assistant", content="answer"),
    ),
    "tool.pre_invoke": EventPayload(tool_name="search", tool_args={"q": "x"}),
    "tool.post_invoke": EventPayload(
        tool_name="search",
        tool_args={"q": "x"},
        tool_result={"r": 1},
    ),
    "output.pre_send": EventPayload(output_text="answer"),
    "session.start": EventPayload(),
    "session.end": EventPayload(),
    "plan.proposed": EventPayload(plan=["step-1"]),
    "plan.approved": EventPayload(plan=["step-1"]),
    "agent.pre_handoff": EventPayload(
        target_agent="b",
        source_agent="a",
        handoff_payload={"k": "v"},
    ),
    "agent.post_handoff": EventPayload(
        target_agent="b",
        source_agent="a",
        handoff_payload={"k": "v"},
    ),
}


class TestBuildPayloadParity:
    def test_expected_payloads_cover_every_event_type(self):
        assert set(_EXPECTED_PAYLOADS) == {e.value for e in EventType}

    def test_build_payload_matches_expected_for_all_events(self):
        ctx = _populated_context()
        for name, expected in _EXPECTED_PAYLOADS.items():
            assert get_event(name).build_payload(ctx) == expected, name


class TestApplyVerdictModifications:
    def test_non_modify_verdict_is_noop(self):
        ctx = LifecycleContext(response_text="unchanged")
        get_event("output.pre_send").apply_verdict_modifications(Verdict.allow(), ctx)
        assert ctx.response_text == "unchanged"

    def test_modify_with_no_modifications_is_noop(self):
        ctx = LifecycleContext(response_text="unchanged")
        get_event("output.pre_send").apply_verdict_modifications(
            Verdict(decision=Decision.MODIFY, modifications=[]),
            ctx,
        )
        assert ctx.response_text == "unchanged"

    def test_replace_modification_is_applied(self):
        ctx = LifecycleContext(response_text="old")
        get_event("output.pre_send").apply_verdict_modifications(
            Verdict.modify(target="output", operation="replace", value="new"),
            ctx,
        )
        assert ctx.response_text == "new"


class TestExecutorInheritance:
    def test_sync_executor_inherits_evaluator(self):
        assert issubclass(
            SyncLifecycleExecutor,
            BaseLifecycleExecutor,
        )

    def test_async_executor_inherits_evaluator(self):
        assert issubclass(
            AsyncLifecycleExecutor,
            BaseLifecycleExecutor,
        )

    def test_streaming_executor_inherits_evaluator(
        self,
    ):
        assert issubclass(
            StreamingLifecycleExecutor,
            BaseLifecycleExecutor,
        )


class _BoomEvent(BaseEvent):
    @property
    def event_type(self) -> EventType:
        return EventType.OUTPUT_PRE_SEND


def _evaluator_with_failing_layer(fail_mode: FailMode) -> PolicyEvaluator:
    layer = PolicyLayer(composition=CompositionConfig(fail_mode=fail_mode))

    async def _raise(*args, **kwargs):
        raise RuntimeError("evaluate blew up")

    # Force the evaluator's failure path without standing up a server.
    layer.evaluate = _raise
    state = InstrumentationState(policy_layer=layer)
    return PolicyEvaluator(state)


class TestEvaluatorFailClosed:
    def test_evaluation_error_denies_by_default(self):
        evaluator = _evaluator_with_failing_layer(FailMode.CLOSED)
        verdict = asyncio.run(
            evaluator.evaluate_event_async(_BoomEvent(), LifecycleContext())
        )
        assert verdict.decision == Decision.DENY

    def test_evaluation_error_allows_when_fail_open(self):
        evaluator = _evaluator_with_failing_layer(FailMode.OPEN)
        verdict = asyncio.run(
            evaluator.evaluate_event_async(_BoomEvent(), LifecycleContext())
        )
        assert verdict.decision == Decision.ALLOW
