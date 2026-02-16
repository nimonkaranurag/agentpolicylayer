from __future__ import annotations

from apl.types import (
    CompositionConfig,
    CompositionMode,
    ContextRequirement,
    Decision,
    Escalation,
    EventPayload,
    EventType,
    FunctionCall,
    Message,
    Modification,
    PolicyDefinition,
    PolicyEvent,
    PolicyManifest,
    SessionMetadata,
    ToolCall,
    Verdict,
)


class TestEventType:

    def test_all_lifecycle_events_have_dotted_values(
        self,
    ):
        for member in EventType:
            assert "." in member.value

    def test_event_type_from_string(self):
        assert (
            EventType("input.received")
            == EventType.INPUT_RECEIVED
        )
        assert (
            EventType("output.pre_send")
            == EventType.OUTPUT_PRE_SEND
        )

    def test_event_type_string_equality(self):
        assert (
            EventType.LLM_PRE_REQUEST
            == "llm.pre_request"
        )


class TestDecision:

    def test_all_decisions_are_lowercase_strings(self):
        for member in Decision:
            assert member.value == member.value.lower()

    def test_five_decision_types_exist(self):
        assert len(Decision) == 5
        names = {d.name for d in Decision}
        assert names == {
            "ALLOW",
            "DENY",
            "MODIFY",
            "ESCALATE",
            "OBSERVE",
        }


class TestMessage:

    def test_minimal_message(self):
        msg = Message(role="user", content="hi")
        assert msg.role == "user"
        assert msg.content == "hi"
        assert msg.tool_calls is None

    def test_assistant_message_with_tool_calls(self):
        tc = ToolCall(
            id="tc-1",
            function=FunctionCall(
                name="search", arguments='{"q":"test"}'
            ),
        )
        msg = Message(
            role="assistant", tool_calls=[tc]
        )
        assert (
            msg.tool_calls[0].function.name == "search"
        )


class TestEventPayload:

    def test_empty_payload(self):
        p = EventPayload()
        assert p.tool_name is None
        assert p.output_text is None
        assert p.llm_model is None

    def test_tool_payload(self):
        p = EventPayload(
            tool_name="calc", tool_args={"x": 1}
        )
        assert p.tool_name == "calc"
        assert p.tool_args["x"] == 1


class TestSessionMetadata:

    def test_defaults(self):
        m = SessionMetadata(session_id="s1")
        assert m.user_id is None
        assert m.token_count == 0
        assert m.user_roles == []
        assert m.cost_usd == 0.0


class TestVerdictFactories:

    def test_allow_default(self):
        v = Verdict.allow()
        assert v.decision == Decision.ALLOW
        assert v.confidence == 1.0
        assert v.reasoning is None

    def test_allow_with_reasoning(self):
        v = Verdict.allow(reasoning="Looks good")
        assert v.reasoning == "Looks good"

    def test_deny_requires_reasoning(self):
        v = Verdict.deny("blocked")
        assert v.decision == Decision.DENY
        assert v.reasoning == "blocked"

    def test_modify_creates_modification(self):
        v = Verdict.modify(
            target="output",
            operation="replace",
            value="redacted",
            reasoning="PII found",
        )
        assert v.decision == Decision.MODIFY
        assert len(v.modifications) == 1
        assert v.modifications[0].target == "output"
        assert (
            v.modifications[0].operation == "replace"
        )
        assert v.modifications[0].value == "redacted"

    def test_modify_with_path(self):
        v = Verdict.modify(
            target="tool_args",
            operation="patch",
            value=42,
            path="$.limit",
        )
        assert v.modifications[0].path == "$.limit"

    def test_escalate_creates_escalation(self):
        v = Verdict.escalate(
            type="human_confirm",
            prompt="Allow deletion?",
            timeout_ms=5000,
            options=["Proceed", "Cancel"],
        )
        assert v.decision == Decision.ESCALATE
        assert v.escalation is not None
        assert v.escalation.type == "human_confirm"
        assert v.escalation.prompt == "Allow deletion?"
        assert v.escalation.timeout_ms == 5000
        assert v.escalation.options == [
            "Proceed",
            "Cancel",
        ]

    def test_observe_with_trace(self):
        trace = {"latency_ms": 42, "cache_hit": True}
        v = Verdict.observe(
            reasoning="monitoring", trace=trace
        )
        assert v.decision == Decision.OBSERVE
        assert v.trace == trace

    def test_confidence_override(self):
        v = Verdict.allow(confidence=0.7)
        assert v.confidence == 0.7


class TestPolicyDefinition:

    def test_definition_defaults(self):
        d = PolicyDefinition(
            name="test",
            version="1.0",
            events=[EventType.OUTPUT_PRE_SEND],
        )
        assert d.blocking is True
        assert d.timeout_ms == 1000
        assert d.context_requirements == []

    def test_definition_with_context(self):
        ctx = ContextRequirement(
            path="metadata.user_region", required=True
        )
        d = PolicyDefinition(
            name="geo-filter",
            version="1.0",
            events=[EventType.INPUT_RECEIVED],
            context_requirements=[ctx],
        )
        assert (
            d.context_requirements[0].path
            == "metadata.user_region"
        )


class TestPolicyManifest:

    def test_manifest_defaults(self):
        m = PolicyManifest(
            server_name="test-server",
            server_version="1.0",
        )
        assert m.protocol_version == "0.3.0"
        assert m.policies == []
        assert m.supports_batch is False

    def test_manifest_with_policies(self):
        p = PolicyDefinition(
            name="p1",
            version="1.0",
            events=[EventType.OUTPUT_PRE_SEND],
        )
        m = PolicyManifest(
            server_name="s",
            server_version="1.0",
            policies=[p],
        )
        assert len(m.policies) == 1


class TestComposition:

    def test_composition_config_defaults(self):
        c = CompositionConfig()
        assert c.mode == CompositionMode.DENY_OVERRIDES
        assert c.parallel is True
        assert c.on_timeout == Decision.ALLOW

    def test_all_composition_modes(self):
        assert len(CompositionMode) == 5
