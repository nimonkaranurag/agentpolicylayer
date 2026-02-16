from __future__ import annotations

from apl.instrumentation.events import (
    EVENT_REGISTRY,
    get_event,
)
from apl.instrumentation.events.agent_post_handoff_event import (
    AgentPostHandoffEvent,
)
from apl.instrumentation.events.agent_pre_handoff_event import (
    AgentPreHandoffEvent,
)
from apl.instrumentation.events.base_event import (
    BaseEvent,
)
from apl.instrumentation.events.input_received_event import (
    InputReceivedEvent,
)
from apl.instrumentation.events.input_validated_event import (
    InputValidatedEvent,
)
from apl.instrumentation.events.llm_post_response_event import (
    LLMPostResponseEvent,
)
from apl.instrumentation.events.llm_pre_request_event import (
    LLMPreRequestEvent,
)
from apl.instrumentation.events.output_pre_send_event import (
    OutputPreSendEvent,
)
from apl.instrumentation.events.plan_approved_event import (
    PlanApprovedEvent,
)
from apl.instrumentation.events.plan_proposed_event import (
    PlanProposedEvent,
)
from apl.instrumentation.events.session_end_event import (
    SessionEndEvent,
)
from apl.instrumentation.events.session_start_event import (
    SessionStartEvent,
)
from apl.instrumentation.events.tool_post_invoke_event import (
    ToolPostInvokeEvent,
)
from apl.instrumentation.events.tool_pre_invoke_event import (
    ToolPreInvokeEvent,
)
from apl.instrumentation.execution import (
    AsyncLifecycleExecutor,
    BaseLifecycleExecutor,
    StreamingLifecycleExecutor,
    SyncLifecycleExecutor,
)
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Modification,
    Verdict,
)


class TestEventRegistry:

    def test_all_thirteen_events_registered(self):
        assert len(EVENT_REGISTRY) == 13

    def test_all_event_type_values_present(self):
        expected_keys = {e.value for e in EventType}
        actual_keys = set(EVENT_REGISTRY.keys())
        assert expected_keys == actual_keys

    def test_get_event_returns_correct_type(self):
        assert isinstance(
            get_event("session.start"),
            SessionStartEvent,
        )
        assert isinstance(
            get_event("output.pre_send"),
            OutputPreSendEvent,
        )
        assert isinstance(
            get_event("tool.pre_invoke"),
            ToolPreInvokeEvent,
        )

    def test_all_events_are_base_event_subclasses(
        self,
    ):
        for event in EVENT_REGISTRY.values():
            assert isinstance(event, BaseEvent)


class TestEventTypes:

    def test_session_start_event_type(self):
        assert (
            SessionStartEvent().event_type
            == EventType.SESSION_START
        )

    def test_session_end_event_type(self):
        assert (
            SessionEndEvent().event_type
            == EventType.SESSION_END
        )

    def test_input_received_event_type(self):
        assert (
            InputReceivedEvent().event_type
            == EventType.INPUT_RECEIVED
        )

    def test_input_validated_event_type(self):
        assert (
            InputValidatedEvent().event_type
            == EventType.INPUT_VALIDATED
        )

    def test_llm_pre_request_event_type(self):
        assert (
            LLMPreRequestEvent().event_type
            == EventType.LLM_PRE_REQUEST
        )

    def test_llm_post_response_event_type(self):
        assert (
            LLMPostResponseEvent().event_type
            == EventType.LLM_POST_RESPONSE
        )

    def test_tool_pre_invoke_event_type(self):
        assert (
            ToolPreInvokeEvent().event_type
            == EventType.TOOL_PRE_INVOKE
        )

    def test_tool_post_invoke_event_type(self):
        assert (
            ToolPostInvokeEvent().event_type
            == EventType.TOOL_POST_INVOKE
        )

    def test_output_pre_send_event_type(self):
        assert (
            OutputPreSendEvent().event_type
            == EventType.OUTPUT_PRE_SEND
        )

    def test_plan_proposed_event_type(self):
        assert (
            PlanProposedEvent().event_type
            == EventType.PLAN_PROPOSED
        )

    def test_plan_approved_event_type(self):
        assert (
            PlanApprovedEvent().event_type
            == EventType.PLAN_APPROVED
        )

    def test_agent_pre_handoff_event_type(self):
        assert (
            AgentPreHandoffEvent().event_type
            == EventType.AGENT_PRE_HANDOFF
        )

    def test_agent_post_handoff_event_type(self):
        assert (
            AgentPostHandoffEvent().event_type
            == EventType.AGENT_POST_HANDOFF
        )


class TestDefaultBuildPayload:

    def test_session_start_returns_empty_payload(self):
        ctx = type(
            "ctx", (), {"proposed_plan": None}
        )()
        payload = SessionStartEvent().build_payload(
            ctx
        )
        assert isinstance(payload, EventPayload)
        assert payload.tool_name is None

    def test_session_end_returns_empty_payload(self):
        ctx = type("ctx", (), {})()
        payload = SessionEndEvent().build_payload(ctx)
        assert isinstance(payload, EventPayload)


class TestApplyVerdictModifications:

    def test_non_modify_verdict_is_noop(self):
        event = SessionStartEvent()
        verdict = Verdict.allow()
        ctx = type("ctx", (), {})()
        event.apply_verdict_modifications(verdict, ctx)

    def test_modify_with_no_modification_is_noop(self):
        event = SessionStartEvent()
        verdict = Verdict(
            decision=Decision.MODIFY, modifications=[]
        )
        ctx = type("ctx", (), {})()
        event.apply_verdict_modifications(verdict, ctx)


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
