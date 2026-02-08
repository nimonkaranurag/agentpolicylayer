"""
APL Core Tests

Basic tests to verify the core functionality works.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime

import pytest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

from apl import (
    CompositionConfig,
    CompositionMode,
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    PolicyServer,
    SessionMetadata,
    Verdict,
)


class TestVerdict:
    """Test Verdict factory methods."""

    def test_allow(self):
        v = Verdict.allow(reasoning="All good")
        assert v.decision == Decision.ALLOW
        assert v.reasoning == "All good"
        assert v.confidence == 1.0

    def test_deny(self):
        v = Verdict.deny(
            reasoning="Blocked", confidence=0.9
        )
        assert v.decision == Decision.DENY
        assert v.reasoning == "Blocked"
        assert v.confidence == 0.9

    def test_modify(self):
        v = Verdict.modify(
            target="output",
            operation="replace",
            value="[REDACTED]",
            reasoning="PII found",
        )
        assert v.decision == Decision.MODIFY
        assert v.modification is not None
        assert v.modification.target == "output"
        assert v.modification.value == "[REDACTED]"

    def test_escalate(self):
        v = Verdict.escalate(
            type="human_confirm",
            prompt="Proceed with delete?",
            options=["Yes", "No"],
        )
        assert v.decision == Decision.ESCALATE
        assert v.escalation is not None
        assert v.escalation.type == "human_confirm"
        assert v.escalation.options == ["Yes", "No"]

    def test_observe(self):
        v = Verdict.observe(
            reasoning="Logged", trace={"action": "test"}
        )
        assert v.decision == Decision.OBSERVE
        assert v.trace == {"action": "test"}


class TestPolicyServer:
    """Test PolicyServer functionality."""

    def test_create_server(self):
        server = PolicyServer(
            "test-server", version="1.0.0"
        )
        assert server.name == "test-server"
        assert server.version == "1.0.0"

    def test_register_policy(self):
        server = PolicyServer("test-server")

        @server.policy(
            name="test-policy",
            events=["output.pre_send"],
            context=["payload.output_text"],
        )
        async def test_policy(event):
            return Verdict.allow()

        assert "test-policy" in server._policies
        assert (
            EventType.OUTPUT_PRE_SEND
            in server._event_handlers
        )

    @pytest.mark.asyncio
    async def test_evaluate_policy(self):
        server = PolicyServer("test-server")

        @server.policy(
            name="always-deny",
            events=["tool.pre_invoke"],
            context=["payload.tool_name"],
        )
        async def always_deny(event):
            return Verdict.deny(reasoning="Always blocked")

        event = PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType.TOOL_PRE_INVOKE,
            timestamp=datetime.utcnow(),
            messages=[],
            payload=EventPayload(tool_name="delete_all"),
            metadata=SessionMetadata(session_id="test"),
        )

        verdicts = await server.evaluate(event)

        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.DENY
        assert verdicts[0].reasoning == "Always blocked"

    @pytest.mark.asyncio
    async def test_policy_timeout(self):
        server = PolicyServer("test-server")

        @server.policy(
            name="slow-policy",
            events=["input.received"],
            timeout_ms=100,
        )
        async def slow_policy(event):
            await asyncio.sleep(
                1
            )  # Sleep longer than timeout
            return Verdict.deny(
                reasoning="Should not reach"
            )

        event = PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType.INPUT_RECEIVED,
            timestamp=datetime.utcnow(),
            messages=[],
            payload=EventPayload(),
            metadata=SessionMetadata(session_id="test"),
        )

        verdicts = await server.evaluate(event)

        # Should allow on timeout (fail-open)
        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.ALLOW
        assert "timed out" in verdicts[0].reasoning

    def test_manifest_generation(self):
        server = PolicyServer(
            "test-server", description="A test server"
        )

        @server.policy(
            name="policy-a",
            events=["input.received"],
            description="First policy",
        )
        async def policy_a(event):
            return Verdict.allow()

        @server.policy(
            name="policy-b",
            events=["output.pre_send", "tool.pre_invoke"],
        )
        async def policy_b(event):
            return Verdict.allow()

        manifest = server.get_manifest()

        assert manifest.server_name == "test-server"
        assert manifest.description == "A test server"
        assert len(manifest.policies) == 2

        policy_names = [p.name for p in manifest.policies]
        assert "policy-a" in policy_names
        assert "policy-b" in policy_names


class TestEventTypes:
    """Test event type handling."""

    def test_event_type_enum(self):
        assert (
            EventType.INPUT_RECEIVED.value
            == "input.received"
        )
        assert (
            EventType.TOOL_PRE_INVOKE.value
            == "tool.pre_invoke"
        )
        assert (
            EventType.OUTPUT_PRE_SEND.value
            == "output.pre_send"
        )

    def test_event_type_from_string(self):
        et = EventType("tool.pre_invoke")
        assert et == EventType.TOOL_PRE_INVOKE


class TestMessage:
    """Test chat/completions compatible Message format."""

    def test_user_message(self):
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_assistant_message_with_tool_calls(self):
        from apl import FunctionCall, ToolCall

        msg = Message(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_123",
                    function=FunctionCall(
                        name="search",
                        arguments='{"query": "test"}',
                    ),
                )
            ],
        )

        assert msg.role == "assistant"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].function.name == "search"


class TestSessionMetadata:
    """Test session metadata handling."""

    def test_default_values(self):
        meta = SessionMetadata(session_id="test-123")
        assert meta.session_id == "test-123"
        assert meta.token_count == 0
        assert meta.cost_usd == 0.0
        assert meta.user_roles == []

    def test_budget_tracking(self):
        meta = SessionMetadata(
            session_id="test-123",
            token_count=5000,
            token_budget=10000,
            cost_usd=0.05,
            cost_budget_usd=1.00,
        )

        assert meta.token_count / meta.token_budget == 0.5
        assert meta.cost_usd / meta.cost_budget_usd == 0.05


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
