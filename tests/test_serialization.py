from __future__ import annotations

from apl.serialization import (
    EventSerializer,
    VerdictSerializer,
)
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    Verdict,
)


class TestVerdictSerializer:

    def setup_method(self):
        self.serializer = VerdictSerializer()

    def test_serialize_allow(self):
        v = Verdict.allow(reasoning="ok")
        data = self.serializer.serialize(v)
        assert data["decision"] == "allow"
        assert data["confidence"] == 1.0
        assert data["reasoning"] == "ok"

    def test_serialize_deny(self):
        data = self.serializer.serialize(
            Verdict.deny("blocked")
        )
        assert data["decision"] == "deny"

    def test_serialize_modify_includes_modification(
        self,
    ):
        v = Verdict.modify(
            target="output",
            operation="replace",
            value="***",
        )
        data = self.serializer.serialize(v)
        assert (
            data["modifications"][0]["target"]
            == "output"
        )
        assert (
            data["modifications"][0]["value"] == "***"
        )

    def test_serialize_escalate_includes_escalation(
        self,
    ):
        v = Verdict.escalate(
            type="human_confirm",
            prompt="proceed?",
            options=["yes", "no"],
        )
        data = self.serializer.serialize(v)
        assert (
            data["escalation"]["type"]
            == "human_confirm"
        )
        assert data["escalation"]["options"] == [
            "yes",
            "no",
        ]

    def test_serialize_omits_none_fields(self):
        data = self.serializer.serialize(
            Verdict.allow()
        )
        assert "reasoning" not in data
        assert "modifications" not in data
        assert "escalation" not in data
        assert "trace" not in data

    def test_roundtrip_allow(self):
        original = Verdict.allow(
            reasoning="good", confidence=0.95
        )
        restored = self.serializer.deserialize(
            self.serializer.serialize(original)
        )
        assert restored.decision == original.decision
        assert (
            restored.confidence == original.confidence
        )
        assert restored.reasoning == original.reasoning

    def test_roundtrip_deny(self):
        original = Verdict.deny("bad", confidence=0.8)
        restored = self.serializer.deserialize(
            self.serializer.serialize(original)
        )
        assert restored.decision == Decision.DENY
        assert restored.reasoning == "bad"

    def test_roundtrip_modify(self):
        original = Verdict.modify(
            target="output",
            operation="redact",
            value="[REDACTED]",
            path="$.content",
        )
        restored = self.serializer.deserialize(
            self.serializer.serialize(original)
        )
        assert (
            restored.modifications[0].target
            == "output"
        )
        assert (
            restored.modifications[0].path
            == "$.content"
        )

    def test_roundtrip_escalate(self):
        original = Verdict.escalate(
            type="human_review",
            prompt="check this",
            timeout_ms=3000,
        )
        restored = self.serializer.deserialize(
            self.serializer.serialize(original)
        )
        assert (
            restored.escalation.type == "human_review"
        )
        assert restored.escalation.timeout_ms == 3000

    def test_deserialize_minimal(self):
        v = self.serializer.deserialize(
            {"decision": "allow"}
        )
        assert v.decision == Decision.ALLOW
        assert v.confidence == 1.0


class TestEventSerializer:

    def setup_method(self):
        self.serializer = EventSerializer()

    def test_serialize_event(
        self, sample_event: PolicyEvent
    ):
        data = self.serializer.serialize(sample_event)
        assert data["type"] == "output.pre_send"
        assert isinstance(data["messages"], list)
        assert isinstance(data["payload"], dict)
        assert isinstance(data["metadata"], dict)
        assert "timestamp" in data
        assert "id" in data

    def test_roundtrip_event(
        self, sample_event: PolicyEvent
    ):
        data = self.serializer.serialize(sample_event)
        restored = self.serializer.deserialize(data)
        assert restored.type == sample_event.type
        assert restored.id == sample_event.id
        assert len(restored.messages) == len(
            sample_event.messages
        )
        assert (
            restored.payload.output_text
            == sample_event.payload.output_text
        )
        assert (
            restored.metadata.session_id
            == sample_event.metadata.session_id
        )

    def test_serialize_messages_content(
        self, sample_event: PolicyEvent
    ):
        data = self.serializer.serialize(sample_event)
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][1]["role"] == "user"

    def test_deserialize_minimal(self):
        data = {
            "type": "input.received",
            "messages": [
                {"role": "user", "content": "hello"}
            ],
        }
        event = self.serializer.deserialize(data)
        assert event.type == EventType.INPUT_RECEIVED
        assert len(event.messages) == 1
        assert event.messages[0].content == "hello"

    def test_deserialize_empty(self):
        event = self.serializer.deserialize({})
        assert event.type == EventType.INPUT_RECEIVED
        assert event.messages == []
