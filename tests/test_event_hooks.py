"""
APL Event Hook Lifecycle Tests

Ensures that every ``EventType`` in the APL protocol can be:
    1. Created as a ``PolicyEvent``
    2. Dispatched to a ``PolicyServer``
    3. Handled by a registered policy
    4. Returned as the correct ``Verdict``

Also verifies that the auto-instrumentation wrappers emit the correct
event types (``llm.pre_request`` and ``output.pre_send``) when
intercepting provider calls.

Event types tested:
    - input.received
    - input.validated
    - plan.proposed
    - plan.approved
    - llm.pre_request
    - llm.post_response
    - tool.pre_invoke
    - tool.post_invoke
    - agent.pre_handoff
    - agent.post_handoff
    - output.pre_send
    - session.start
    - session.end
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

import apl
import apl.instrument as inst
from apl import (
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    PolicyServer,
    SessionMetadata,
    Verdict,
)
from apl.instrument import _instrumented
from tests.conftest import (
    OPENAI_RESPONSE_CONTENT,
    make_event,
)

# ============================================================================
# Helpers
# ============================================================================


def _server_for_event(
    event_type_str: str,
    decision: Decision = Decision.ALLOW,
    reasoning: str = "test",
):
    """Create a PolicyServer with a single policy that handles *event_type_str*."""
    server = PolicyServer("hook-test")

    @server.policy(
        name=f"test-{event_type_str.replace('.', '-')}",
        events=[event_type_str],
    )
    async def handler(event):
        if decision == Decision.ALLOW:
            return Verdict.allow(reasoning=reasoning)
        elif decision == Decision.DENY:
            return Verdict.deny(reasoning=reasoning)
        elif decision == Decision.MODIFY:
            return Verdict.modify(
                target="output",
                operation="replace",
                value="modified",
                reasoning=reasoning,
            )
        elif decision == Decision.ESCALATE:
            return Verdict.escalate(
                type="human_confirm",
                prompt=reasoning,
            )
        else:
            return Verdict.observe(reasoning=reasoning)

    return server


def _make_full_event(event_type_str: str) -> PolicyEvent:
    """Build a ``PolicyEvent`` for *event_type_str* with reasonable defaults."""
    et = EventType(event_type_str)

    payload_kw = {}
    if "tool" in event_type_str:
        payload_kw["tool_name"] = "test_tool"
        payload_kw["tool_args"] = {"key": "value"}
    if "llm" in event_type_str:
        payload_kw["llm_model"] = "test-model"
    if "output" in event_type_str:
        payload_kw["output_text"] = "test output"
    if "handoff" in event_type_str:
        payload_kw["target_agent"] = "agent-b"
        payload_kw["source_agent"] = "agent-a"
    if "plan" in event_type_str:
        payload_kw["plan"] = [
            "step-1",
            "step-2",
        ]

    return PolicyEvent(
        id=str(uuid.uuid4()),
        type=et,
        timestamp=datetime.utcnow(),
        messages=[
            Message(role="user", content="test message")
        ],
        payload=EventPayload(**payload_kw),
        metadata=SessionMetadata(session_id="test"),
    )


# ============================================================================
# Every EventType can be dispatched & handled
# ============================================================================


ALL_EVENT_TYPES = [
    "input.received",
    "input.validated",
    "plan.proposed",
    "plan.approved",
    "llm.pre_request",
    "llm.post_response",
    "tool.pre_invoke",
    "tool.post_invoke",
    "agent.pre_handoff",
    "agent.post_handoff",
    "output.pre_send",
    "session.start",
    "session.end",
]


class TestEventDispatching:
    """Each event type can be dispatched to a server and handled correctly."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
    async def test_event_type_allow(self, event_type):
        """A server with an ALLOW handler returns ALLOW for *event_type*."""
        server = _server_for_event(event_type)
        event = _make_full_event(event_type)
        verdicts = await server.evaluate(event)
        assert len(verdicts) >= 1
        assert verdicts[0].decision == Decision.ALLOW

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
    async def test_event_type_deny(self, event_type):
        """A server with a DENY handler returns DENY for *event_type*."""
        server = _server_for_event(
            event_type,
            decision=Decision.DENY,
            reasoning="blocked",
        )
        event = _make_full_event(event_type)
        verdicts = await server.evaluate(event)
        assert verdicts[0].decision == Decision.DENY
        assert verdicts[0].reasoning == "blocked"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
    async def test_event_type_modify(self, event_type):
        """A server with a MODIFY handler returns MODIFY for *event_type*."""
        server = _server_for_event(
            event_type, decision=Decision.MODIFY
        )
        event = _make_full_event(event_type)
        verdicts = await server.evaluate(event)
        assert verdicts[0].decision == Decision.MODIFY
        assert verdicts[0].modification is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
    async def test_event_type_escalate(self, event_type):
        """A server with an ESCALATE handler returns ESCALATE for *event_type*."""
        server = _server_for_event(
            event_type, decision=Decision.ESCALATE
        )
        event = _make_full_event(event_type)
        verdicts = await server.evaluate(event)
        assert verdicts[0].decision == Decision.ESCALATE
        assert verdicts[0].escalation is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
    async def test_event_type_observe(self, event_type):
        """A server with an OBSERVE handler returns OBSERVE for *event_type*."""
        server = _server_for_event(
            event_type, decision=Decision.OBSERVE
        )
        event = _make_full_event(event_type)
        verdicts = await server.evaluate(event)
        assert verdicts[0].decision == Decision.OBSERVE


# ============================================================================
# No-handler fallback
# ============================================================================


class TestNoHandlerFallback:
    """Events with no matching handler return a default ALLOW."""

    @pytest.mark.asyncio
    async def test_unregistered_event_returns_allow(self):
        server = PolicyServer("empty")
        event = _make_full_event("input.received")
        verdicts = await server.evaluate(event)
        assert verdicts[0].decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_mismatched_event_returns_allow(self):
        """A server only handles tool.pre_invoke; input.received falls through."""
        server = _server_for_event("tool.pre_invoke")
        event = _make_full_event("input.received")
        verdicts = await server.evaluate(event)
        assert verdicts[0].decision == Decision.ALLOW


# ============================================================================
# Multiple handlers for the same event
# ============================================================================


class TestMultipleHandlers:
    """Multiple policies registered for the same event all fire."""

    @pytest.mark.asyncio
    async def test_two_handlers_both_fire(self):
        server = PolicyServer("multi")
        call_log = []

        @server.policy(
            name="handler-a",
            events=["output.pre_send"],
        )
        async def handler_a(event):
            call_log.append("a")
            return Verdict.allow(reasoning="from-a")

        @server.policy(
            name="handler-b",
            events=["output.pre_send"],
        )
        async def handler_b(event):
            call_log.append("b")
            return Verdict.observe(reasoning="from-b")

        event = _make_full_event("output.pre_send")
        verdicts = await server.evaluate(event)

        assert len(verdicts) == 2
        assert set(call_log) == {"a", "b"}
        decisions = {v.decision for v in verdicts}
        assert Decision.ALLOW in decisions
        assert Decision.OBSERVE in decisions

    @pytest.mark.asyncio
    async def test_one_deny_among_allows(self):
        """If one policy denies, it is present among the verdicts."""
        server = PolicyServer("mixed")

        @server.policy(
            name="allow-policy",
            events=["tool.pre_invoke"],
        )
        async def allow_p(event):
            return Verdict.allow()

        @server.policy(
            name="deny-policy",
            events=["tool.pre_invoke"],
        )
        async def deny_p(event):
            return Verdict.deny(reasoning="forbidden")

        event = _make_full_event("tool.pre_invoke")
        verdicts = await server.evaluate(event)
        assert any(
            v.decision == Decision.DENY for v in verdicts
        )


# ============================================================================
# Cross-event handler
# ============================================================================


class TestCrossEventHandler:
    """A single policy can subscribe to multiple event types."""

    @pytest.mark.asyncio
    async def test_single_policy_multiple_events(self):
        server = PolicyServer("cross")

        @server.policy(
            name="multi-event",
            events=[
                "llm.pre_request",
                "output.pre_send",
            ],
        )
        async def multi(event):
            return Verdict.allow(
                reasoning=f"handled {event.type.value}"
            )

        for et in ["llm.pre_request", "output.pre_send"]:
            event = _make_full_event(et)
            verdicts = await server.evaluate(event)
            assert verdicts[0].decision == Decision.ALLOW
            assert et in verdicts[0].reasoning


# ============================================================================
# Instrumentation emits the right event types
# ============================================================================


class TestInstrumentationEventTypes:
    """
    Verify that provider wrappers evaluate the correct lifecycle events.
    The sync wrappers evaluate ``llm.pre_request`` before the call and
    ``output.pre_send`` after it.
    """

    def test_openai_emits_correct_events(self):
        apl.auto_instrument(
            policy_servers=[],
            instrument_openai=True,
            instrument_anthropic=False,
            instrument_litellm=False,
            instrument_langchain=False,
            instrument_watsonx=False,
        )

        captured_event_types = []

        async def spy_pre(messages, model):
            captured_event_types.append("llm.pre_request")
            return Verdict.allow()

        async def spy_post(output_text, messages):
            captured_event_types.append("output.pre_send")
            return Verdict.allow()

        with (
            patch.object(
                inst,
                "_evaluate_pre_request",
                side_effect=spy_pre,
            ),
            patch.object(
                inst,
                "_evaluate_post_response",
                side_effect=spy_post,
            ),
        ):
            from openai import OpenAI

            client = OpenAI()
            client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
            )

        assert captured_event_types == [
            "llm.pre_request",
            "output.pre_send",
        ]

    def test_anthropic_emits_correct_events(self):
        apl.auto_instrument(
            policy_servers=[],
            instrument_openai=False,
            instrument_anthropic=True,
            instrument_litellm=False,
            instrument_langchain=False,
            instrument_watsonx=False,
        )

        captured = []

        async def spy_pre(messages, model):
            captured.append("llm.pre_request")
            return Verdict.allow()

        async def spy_post(output_text, messages):
            captured.append("output.pre_send")
            return Verdict.allow()

        with (
            patch.object(
                inst,
                "_evaluate_pre_request",
                side_effect=spy_pre,
            ),
            patch.object(
                inst,
                "_evaluate_post_response",
                side_effect=spy_post,
            ),
        ):
            from anthropic import Anthropic

            client = Anthropic()
            client.messages.create(
                model="claude-sonnet-4-5-20250929",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
                max_tokens=100,
            )

        assert captured == [
            "llm.pre_request",
            "output.pre_send",
        ]

    def test_watsonx_emits_correct_events(self):
        apl.auto_instrument(
            policy_servers=[],
            instrument_openai=False,
            instrument_anthropic=False,
            instrument_litellm=False,
            instrument_langchain=False,
            instrument_watsonx=True,
        )

        captured = []

        async def spy_pre(messages, model):
            captured.append("llm.pre_request")
            return Verdict.allow()

        async def spy_post(output_text, messages):
            captured.append("output.pre_send")
            return Verdict.allow()

        with (
            patch.object(
                inst,
                "_evaluate_pre_request",
                side_effect=spy_pre,
            ),
            patch.object(
                inst,
                "_evaluate_post_response",
                side_effect=spy_post,
            ),
        ):
            from ibm_watsonx_ai.foundation_models import (
                ModelInference,
            )

            model = ModelInference(
                model_id="ibm/granite-chat"
            )
            model.chat(
                messages=[{"role": "user", "content": "hi"}]
            )

        assert captured == [
            "llm.pre_request",
            "output.pre_send",
        ]

    def test_litellm_emits_correct_events(self):
        apl.auto_instrument(
            policy_servers=[],
            instrument_openai=False,
            instrument_anthropic=False,
            instrument_litellm=True,
            instrument_langchain=False,
            instrument_watsonx=False,
        )

        captured = []

        async def spy_pre(messages, model):
            captured.append("llm.pre_request")
            return Verdict.allow()

        async def spy_post(output_text, messages):
            captured.append("output.pre_send")
            return Verdict.allow()

        with (
            patch.object(
                inst,
                "_evaluate_pre_request",
                side_effect=spy_pre,
            ),
            patch.object(
                inst,
                "_evaluate_post_response",
                side_effect=spy_post,
            ),
        ):
            import litellm

            litellm.completion(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
            )

        assert captured == [
            "llm.pre_request",
            "output.pre_send",
        ]

    def test_langchain_emits_correct_events(self):
        apl.auto_instrument(
            policy_servers=[],
            instrument_openai=False,
            instrument_anthropic=False,
            instrument_litellm=False,
            instrument_langchain=True,
            instrument_watsonx=False,
        )

        captured = []

        async def spy_pre(messages, model):
            captured.append("llm.pre_request")
            return Verdict.allow()

        async def spy_post(output_text, messages):
            captured.append("output.pre_send")
            return Verdict.allow()

        with (
            patch.object(
                inst,
                "_evaluate_pre_request",
                side_effect=spy_pre,
            ),
            patch.object(
                inst,
                "_evaluate_post_response",
                side_effect=spy_post,
            ),
        ):
            from langchain_core.language_models.chat_models import (
                BaseChatModel,
            )

            model = BaseChatModel()
            model.invoke("Hello")

        assert captured == [
            "llm.pre_request",
            "output.pre_send",
        ]


# ============================================================================
# EventType enum coverage
# ============================================================================


class TestEventTypeEnum:
    """Basic enum sanity checks."""

    def test_all_event_types_parseable(self):
        """Every string in ALL_EVENT_TYPES resolves to a valid EventType."""
        for et_str in ALL_EVENT_TYPES:
            et = EventType(et_str)
            assert et.value == et_str

    def test_event_type_count(self):
        """We test at least as many events as are defined in the enum."""
        assert len(ALL_EVENT_TYPES) == len(EventType)


# ============================================================================
# Policy metadata on verdicts
# ============================================================================


class TestVerdictMetadata:
    """Verify that policy name, version, and timing are attached."""

    @pytest.mark.asyncio
    async def test_verdict_has_policy_name(self):
        server = PolicyServer("meta-test")

        @server.policy(
            name="named-policy",
            events=["input.received"],
            version="2.0.0",
        )
        async def named(event):
            return Verdict.allow()

        event = _make_full_event("input.received")
        verdicts = await server.evaluate(event)
        v = verdicts[0]
        assert v.policy_name == "named-policy"
        assert v.policy_version == "2.0.0"
        assert v.evaluation_ms is not None
        assert v.evaluation_ms >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
