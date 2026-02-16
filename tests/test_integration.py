from __future__ import annotations

import pytest

from apl.composition import VerdictComposer
from apl.declarative_engine.condition_evaluator import (
    ConditionEvaluator,
)
from apl.declarative_engine.rule_evaluator import (
    RuleEvaluator,
)
from apl.declarative_engine.schema import YAMLRule
from apl.serialization import (
    EventSerializer,
    VerdictSerializer,
)
from apl.server import PolicyServer
from apl.types import (
    CompositionConfig,
    CompositionMode,
    Decision,
    EventPayload,
    EventType,
    Message,
    SessionMetadata,
    Verdict,
)


class TestEndToEndPolicyEvaluation:

    @pytest.mark.asyncio
    async def test_full_server_evaluation_flow(
        self, make_event
    ):
        server = PolicyServer("integration-test")

        @server.policy(
            name="pii-filter",
            events=["output.pre_send"],
        )
        async def pii_filter(event):
            text = event.payload.output_text or ""
            if "SSN" in text or "password" in text:
                return Verdict.deny(
                    "PII detected in output"
                )
            return Verdict.allow()

        @server.policy(
            name="length-check",
            events=["output.pre_send"],
        )
        async def length_check(event):
            text = event.payload.output_text or ""
            if len(text) > 10000:
                return Verdict.modify(
                    target="output",
                    operation="replace",
                    value=text[:10000] + "...",
                    reasoning="Output truncated",
                )
            return Verdict.allow()

        safe_event = make_event(
            event_type=EventType.OUTPUT_PRE_SEND,
            payload=EventPayload(
                output_text="Hello, this is safe."
            ),
        )
        verdicts = await server.evaluate(safe_event)
        assert len(verdicts) == 2
        assert all(
            v.decision == Decision.ALLOW
            for v in verdicts
        )

        unsafe_event = make_event(
            event_type=EventType.OUTPUT_PRE_SEND,
            payload=EventPayload(
                output_text="Your SSN is 123-45-6789"
            ),
        )
        verdicts = await server.evaluate(unsafe_event)
        deny_verdicts = [
            v
            for v in verdicts
            if v.decision == Decision.DENY
        ]
        assert len(deny_verdicts) == 1
        assert "PII" in deny_verdicts[0].reasoning

    @pytest.mark.asyncio
    async def test_composition_after_evaluation(
        self, make_event
    ):
        server = PolicyServer("composition-test")

        @server.policy(
            name="strict", events=["input.received"]
        )
        async def strict(event):
            return Verdict.deny("always deny")

        @server.policy(
            name="lenient", events=["input.received"]
        )
        async def lenient(event):
            return Verdict.allow(
                reasoning="always allow"
            )

        event = make_event(
            event_type=EventType.INPUT_RECEIVED
        )
        verdicts = await server.evaluate(event)

        deny_composer = VerdictComposer(
            CompositionConfig(
                mode=CompositionMode.DENY_OVERRIDES
            )
        )
        result = deny_composer.compose(verdicts)
        assert result.decision == Decision.DENY

        allow_composer = VerdictComposer(
            CompositionConfig(
                mode=CompositionMode.ALLOW_OVERRIDES
            )
        )
        result = allow_composer.compose(verdicts)
        assert result.decision == Decision.ALLOW


class TestEndToEndSerialization:

    def test_event_serialize_deserialize_with_full_data(
        self,
    ):
        from apl.layer.event_builder import (
            PolicyEventBuilder,
        )

        builder = PolicyEventBuilder()
        event = builder.build_from_evaluation_args(
            event_type=EventType.LLM_PRE_REQUEST,
            messages=[
                Message(
                    role="system",
                    content="You are helpful.",
                ),
                Message(
                    role="user",
                    content="Explain quantum computing.",
                ),
            ],
            payload=EventPayload(llm_model="gpt-4"),
            metadata=SessionMetadata(
                session_id="s-integration",
                user_id="u-42",
                user_region="US",
                user_roles=["admin", "developer"],
            ),
        )

        serializer = EventSerializer()
        data = serializer.serialize(event)
        restored = serializer.deserialize(data)

        assert (
            restored.type == EventType.LLM_PRE_REQUEST
        )
        assert len(restored.messages) == 2
        assert restored.messages[0].role == "system"
        assert restored.payload.llm_model == "gpt-4"
        assert restored.metadata.user_id == "u-42"
        assert restored.metadata.user_region == "US"

    def test_verdict_roundtrip_all_types(self):
        serializer = VerdictSerializer()

        for verdict in [
            Verdict.allow(reasoning="ok"),
            Verdict.deny("no"),
            Verdict.modify(
                target="output",
                operation="replace",
                value="x",
            ),
            Verdict.escalate(
                type="human_confirm", prompt="check"
            ),
            Verdict.observe(trace={"key": "val"}),
        ]:
            data = serializer.serialize(verdict)
            restored = serializer.deserialize(data)
            assert (
                restored.decision == verdict.decision
            )


class TestEndToEndDeclarativeRules:

    def test_multi_rule_first_match_wins(self):
        evaluator = RuleEvaluator()
        builder = __import__(
            "apl.layer.event_builder",
            fromlist=["PolicyEventBuilder"],
        ).PolicyEventBuilder()

        rules = [
            YAMLRule(
                when={
                    "payload.output_text": {
                        "contains": "SECRET"
                    }
                },
                then={
                    "decision": "deny",
                    "reasoning": "secret detected",
                },
            ),
            YAMLRule(
                when={"metadata.user_region": "EU"},
                then={
                    "decision": "modify",
                    "reasoning": "GDPR compliance",
                    "modification": {
                        "target": "output",
                        "operation": "redact",
                        "value": "[REDACTED]",
                    },
                },
            ),
            YAMLRule(
                when={},
                then={"decision": "allow"},
            ),
        ]

        event = builder.build_from_evaluation_args(
            event_type=EventType.OUTPUT_PRE_SEND,
            payload=EventPayload(
                output_text="This has SECRET data"
            ),
            metadata=SessionMetadata(
                session_id="s1", user_region="EU"
            ),
        )

        for rule in rules:
            result = (
                evaluator.evaluate_rule_against_event(
                    rule, event
                )
            )
            if result is not None:
                assert result.decision == Decision.DENY
                break

    def test_condition_evaluator_composability(self):
        evaluator = ConditionEvaluator()

        evaluator.register_condition(
            "between",
            lambda val, bounds: bounds[0]
            <= val
            <= bounds[1],
        )

        assert (
            evaluator.evaluate(5, {"between": [1, 10]})
            is True
        )
        assert (
            evaluator.evaluate(
                15, {"between": [1, 10]}
            )
            is False
        )

        assert (
            evaluator.evaluate(
                5, {"all": [{"gt": 0}, {"lt": 10}]}
            )
            is True
        )
        assert (
            evaluator.evaluate(
                5, {"any": [{"lt": 3}, {"gt": 4}]}
            )
            is True
        )
