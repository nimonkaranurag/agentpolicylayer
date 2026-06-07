from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from apl.layer.client_transports.base_client_transport import BaseClientTransport
from apl.layer.policy_client import PolicyClient, _assert_protocol_compatible
from apl.serialization import (
    event_from_wire,
    manifest_from_wire,
    to_wire,
    verdict_from_wire,
)
from apl.types import (
    PROTOCOL_VERSION,
    ContextRequirement,
    Decision,
    EventPayload,
    EventType,
    FunctionCall,
    Message,
    PolicyDefinition,
    PolicyEvent,
    PolicyManifest,
    PolicyUnavailableError,
    SessionMetadata,
    ToolCall,
    Verdict,
)

# A spread of fully/partially populated instances covering every field, enum,
# datetime, nested model, and the empty-list edge — the property-based round-trip
# corpus. Each must survive ``model_validate(to_wire(x)) == x`` losslessly.
_ROUND_TRIP_CORPUS = [
    Verdict.allow(reasoning="ok", confidence=0.9),
    Verdict.deny("blocked", confidence=0.5),
    Verdict.modify(
        target="output",
        operation="redact",
        value="[REDACTED]",
        path="$.content",
        reasoning="pii",
        confidence=0.75,
    ),
    Verdict.escalate(
        type="human_confirm",
        prompt="proceed?",
        timeout_ms=3000,
        fallback_action="abort",
        options=["yes", "no"],
        reasoning="risky",
    ),
    Verdict.observe(reasoning="watching", trace={"latency_ms": 12, "hit": True}),
    Verdict(
        decision=Decision.ALLOW,
        confidence=1.0,
        reasoning="full",
        policy_name="p1",
        policy_version="2.0",
        evaluation_ms=4.2,
        trace={"k": "v"},
    ),
    Message(role="system", content="be good"),
    Message(role="user", content="hi", name="u1"),
    Message(
        role="assistant",
        tool_calls=[
            ToolCall(id="c1", function=FunctionCall(name="search", arguments='{"q":1}'))
        ],
    ),
    Message(role="tool", content="result", tool_call_id="c1"),
    EventPayload(),  # all-None payload
    EventPayload(llm_prompt=[]),  # the empty-list edge (§3.12)
    EventPayload(
        tool_name="calc",
        tool_args={"x": 1},
        tool_result={"y": 2},
        tool_error=None,
        llm_model="gpt-4",
        llm_prompt=[Message(role="user", content="q")],
        llm_response=Message(role="assistant", content="a"),
        llm_tokens_used=42,
        output_text="done",
        output_structured={"ok": True},
        plan=["step1", "step2"],
        target_agent="b",
        source_agent="a",
        handoff_payload={"k": "v"},
    ),
    SessionMetadata(session_id="s1"),
    SessionMetadata(
        session_id="s2",
        user_id="u",
        agent_id="ag",
        token_count=10,
        token_budget=100,
        cost_usd=0.5,
        cost_budget_usd=5.0,
        user_roles=["admin", "dev"],
        user_region="EU",
        compliance_tags=["gdpr"],
        custom={"team": "x"},
    ),
    ContextRequirement(path="metadata.user_region", required=True, description="geo"),
    PolicyDefinition(
        name="p",
        version="1.0",
        events=[EventType.OUTPUT_PRE_SEND, EventType.TOOL_PRE_INVOKE],
        context_requirements=[ContextRequirement(path="metadata.user_id")],
        blocking=False,
        timeout_ms=250,
        description="d",
        author="me",
        tags=["t1"],
    ),
    PolicyManifest(
        server_name="srv",
        server_version="1.2.3",
        policies=[
            PolicyDefinition(name="a", version="1", events=[EventType.SESSION_START])
        ],
        supports_batch=True,
        supports_streaming=True,
        description="desc",
        documentation_url="https://x",
    ),
]


class TestWireRoundTripLossless:
    @pytest.mark.parametrize(
        "original",
        _ROUND_TRIP_CORPUS,
        ids=lambda o: type(o).__name__ + ":" + str(getattr(o, "decision", ""))[:12],
    )
    def test_model_survives_round_trip(self, original):
        restored = type(original).model_validate(to_wire(original))
        assert restored == original

    def test_full_event_round_trip_is_lossless(self, sample_event: PolicyEvent):
        restored = event_from_wire(to_wire(sample_event))
        assert restored == sample_event

    def test_wire_output_is_json_native(self):
        # to_wire must produce a dict json.dumps can serialize directly (datetimes
        # become ISO strings, enums become their values) — the transports rely on it.
        payload = EventPayload(
            llm_prompt=[Message(role="user", content="q")],
            output_text="x",
        )
        event = PolicyEvent(
            type=EventType.LLM_PRE_REQUEST,
            payload=payload,
            metadata=SessionMetadata(session_id="s"),
        )
        json.dumps(to_wire(event))  # must not raise


class TestToWireSemantics:
    def test_none_fields_are_omitted(self):
        data = to_wire(Verdict.allow())
        assert "reasoning" not in data
        assert "escalation" not in data
        assert "trace" not in data
        assert "policy_name" not in data

    def test_confidence_is_always_present(self):
        # Even at the default it is emitted; weighted composition needs it.
        assert to_wire(Verdict.allow())["confidence"] == 1.0

    def test_enum_is_serialized_as_value(self):
        assert to_wire(Verdict.deny("x"))["decision"] == "deny"
        assert to_wire(PolicyEvent(type=EventType.OUTPUT_PRE_SEND))["type"] == (
            "output.pre_send"
        )

    def test_empty_list_is_preserved_not_collapsed(self):
        # §3.12: an explicit empty list must NOT round-trip to None/absent.
        data = to_wire(EventPayload(llm_prompt=[]))
        assert data["llm_prompt"] == []
        assert event_from_wire({"payload": data}).payload.llm_prompt == []

    def test_absent_optional_list_stays_none(self):
        # The flip side: None is genuinely absent, distinct from [].
        data = to_wire(EventPayload(llm_prompt=None))
        assert "llm_prompt" not in data
        assert event_from_wire({"payload": data}).payload.llm_prompt is None


class TestStartedAtRoundTrip:
    def test_started_at_is_preserved(self):
        # §3.12: previously started_at was serialized but never read back, so it
        # reset to "now" on every hop. It must survive a round trip now.
        started = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        meta = SessionMetadata(session_id="s", started_at=started)
        restored = SessionMetadata.model_validate(to_wire(meta))
        assert restored.started_at == started

    def test_started_at_default_is_timezone_aware(self):
        assert SessionMetadata(session_id="s").started_at.tzinfo is not None


class TestVerdictCodec:
    def test_round_trip_via_codec(self):
        original = Verdict.modify(
            target="output", operation="redact", value="[X]", confidence=0.6
        )
        assert verdict_from_wire(to_wire(original)) == original

    @pytest.mark.parametrize(
        "target",
        [
            "input",
            "tool_args",
            "llm_prompt",
            "output",
            "tool_result",
            "plan",
            "handoff_payload",
        ],
    )
    def test_every_engine_target_is_constructable_and_round_trips(self, target):
        # The Modification.target literal must cover every target the event table
        # (apl/instrumentation/events) can apply, or a built-in capability becomes
        # unconstructable through the Verdict API.
        v = Verdict.modify(target=target, operation="replace", value="x")
        assert verdict_from_wire(to_wire(v)).modifications[0].target == target

    def test_missing_confidence_is_rejected_fail_closed(self):
        # §3.12: a verdict that omits confidence used to default to 1.0 (max),
        # biasing weighted voting. It must now be rejected, not defaulted.
        with pytest.raises(PolicyUnavailableError):
            verdict_from_wire({"decision": "allow"})

    def test_out_of_range_confidence_is_rejected(self):
        with pytest.raises(PolicyUnavailableError):
            verdict_from_wire({"decision": "allow", "confidence": 1.5})
        with pytest.raises(PolicyUnavailableError):
            verdict_from_wire({"decision": "allow", "confidence": -0.1})

    def test_non_dict_payload_is_rejected(self):
        with pytest.raises(PolicyUnavailableError):
            verdict_from_wire(None)  # type: ignore[arg-type]

    def test_modify_without_modifications_is_rejected(self):
        with pytest.raises(PolicyUnavailableError):
            verdict_from_wire({"decision": "modify", "confidence": 1.0})

    def test_escalate_without_escalation_is_rejected(self):
        with pytest.raises(PolicyUnavailableError):
            verdict_from_wire({"decision": "escalate", "confidence": 1.0})

    def test_unknown_decision_is_rejected(self):
        with pytest.raises(PolicyUnavailableError):
            verdict_from_wire({"decision": "banana", "confidence": 1.0})


class TestVerdictInvariantsAtConstruction:
    # The §5.2 invariants hold for Python construction too, not just the wire.
    def test_modify_requires_a_modification(self):
        with pytest.raises(ValidationError):
            Verdict(decision=Decision.MODIFY, modifications=[])

    def test_escalate_requires_an_escalation(self):
        with pytest.raises(ValidationError):
            Verdict(decision=Decision.ESCALATE)

    def test_confidence_must_be_within_unit_interval(self):
        with pytest.raises(ValidationError):
            Verdict(decision=Decision.ALLOW, confidence=2.0)


class TestEventCodec:
    def test_deserialize_minimal(self):
        event = event_from_wire(
            {"type": "input.received", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert event.type == EventType.INPUT_RECEIVED
        assert len(event.messages) == 1
        assert event.messages[0].content == "hi"

    def test_deserialize_empty_uses_defaults(self):
        event = event_from_wire({})
        assert event.type == EventType.INPUT_RECEIVED
        assert event.messages == []

    def test_invalid_event_type_is_rejected(self):
        # Validate-on-deserialize: a bogus event type fails loudly.
        with pytest.raises(ValidationError):
            event_from_wire({"type": "bogus.event"})

    def test_nonstandard_message_role_is_accepted(self):
        # role is intentionally lenient: provider role vocabularies drift (e.g.
        # "function"/"developer"), and instrumentation must not crash on them.
        event = event_from_wire({"messages": [{"role": "function", "content": "x"}]})
        assert event.messages[0].role == "function"


class TestManifestCodec:
    def test_round_trip(self):
        manifest = PolicyManifest(
            server_name="s",
            server_version="1.0",
            policies=[
                PolicyDefinition(
                    name="p",
                    version="1",
                    events=[EventType.OUTPUT_PRE_SEND],
                    context_requirements=[ContextRequirement(path="metadata.user_id")],
                )
            ],
        )
        assert manifest_from_wire(to_wire(manifest)) == manifest

    def test_missing_protocol_version_defaults(self):
        manifest = manifest_from_wire({"server_name": "s", "server_version": "1.0"})
        assert manifest.protocol_version == PROTOCOL_VERSION


class _ManifestTransport(BaseClientTransport):
    """Fake client transport that yields a manifest with a chosen protocol version."""

    def __init__(self, protocol_version: str) -> None:
        self._protocol_version = protocol_version

    async def connect(self) -> dict:
        return {
            "server_name": "fake",
            "server_version": "1.0",
            "protocol_version": self._protocol_version,
            "policies": [],
        }

    async def evaluate(self, serialized_event: dict) -> list[dict]:
        return []

    async def close(self) -> None:
        return None


def _client_with(transport: BaseClientTransport) -> PolicyClient:
    client = PolicyClient("http://policy.test")
    client._transport = transport
    return client


class TestProtocolVersionCompatibility:
    def test_same_version_is_compatible(self):
        _assert_protocol_compatible(PROTOCOL_VERSION, "uri")  # must not raise

    def test_same_major_different_minor_warns_but_passes(self, caplog):
        with caplog.at_level(logging.WARNING, logger="apl"):
            _assert_protocol_compatible("0.99.0", "uri")  # major 0 == ours, ok
        assert any("0.99.0" in r.message for r in caplog.records)

    def test_different_major_is_rejected(self):
        with pytest.raises(PolicyUnavailableError):
            _assert_protocol_compatible("1.0.0", "uri")

    def test_unparseable_version_warns_but_passes(self, caplog):
        with caplog.at_level(logging.WARNING, logger="apl"):
            _assert_protocol_compatible("garbage", "uri")  # must not raise
        assert any("garbage" in r.message for r in caplog.records)

    def test_client_connect_rejects_incompatible_major(self):
        client = _client_with(_ManifestTransport("9.9.9"))
        with pytest.raises(PolicyUnavailableError):
            asyncio.run(client.connect())

    def test_client_evaluate_fails_closed_on_incompatible(self):
        client = _client_with(_ManifestTransport("9.9.9"))
        event = PolicyEvent(type=EventType.INPUT_RECEIVED)
        verdicts = asyncio.run(client.evaluate(event))
        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.DENY  # fail-closed

    def test_client_connect_ok_on_matching_version(self):
        client = _client_with(_ManifestTransport(PROTOCOL_VERSION))
        asyncio.run(client.connect())
        assert client.is_connected
