from __future__ import annotations

import asyncio

import pytest

from apl.layer.client_transports import (
    BaseClientTransport,
    resolve_client_transport_for_uri,
)
from apl.layer.client_transports.http_client_transport import (
    HttpClientTransport,
)
from apl.layer.client_transports.stdio_client_transport import (
    StdioClientTransport,
)
from apl.layer.event_builder import PolicyEventBuilder
from apl.layer.exceptions import (
    PolicyDenied,
    PolicyEscalation,
)
from apl.layer.policy_client import PolicyClient
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    FailMode,
    Message,
    PolicyUnavailableError,
    SessionMetadata,
    Verdict,
)


class TestPolicyEventBuilder:

    def setup_method(self):
        self.builder = PolicyEventBuilder()

    def test_build_minimal_event(self):
        event = self.builder.build_from_evaluation_args(
            event_type=EventType.OUTPUT_PRE_SEND,
        )
        assert event.type == EventType.OUTPUT_PRE_SEND
        assert event.messages == []
        assert event.payload.output_text is None
        assert event.metadata.session_id is not None
        assert event.id is not None
        assert event.timestamp is not None

    def test_build_with_string_event_type(self):
        event = self.builder.build_from_evaluation_args(event_type="input.received")
        assert event.type == EventType.INPUT_RECEIVED

    def test_build_with_messages(self):
        messages = [Message(role="user", content="hi")]
        event = self.builder.build_from_evaluation_args(
            event_type=EventType.INPUT_RECEIVED,
            messages=messages,
        )
        assert len(event.messages) == 1
        assert event.messages[0].content == "hi"

    def test_build_with_payload(self):
        payload = EventPayload(output_text="hello")
        event = self.builder.build_from_evaluation_args(
            event_type=EventType.OUTPUT_PRE_SEND,
            payload=payload,
        )
        assert event.payload.output_text == "hello"

    def test_build_with_metadata(self):
        meta = SessionMetadata(session_id="s-123", user_id="u-1")
        event = self.builder.build_from_evaluation_args(
            event_type=EventType.OUTPUT_PRE_SEND,
            metadata=meta,
        )
        assert event.metadata.session_id == "s-123"
        assert event.metadata.user_id == "u-1"

    def test_invalid_string_event_type_raises(self):
        with pytest.raises(ValueError):
            self.builder.build_from_evaluation_args(event_type="nonexistent.event")


class TestTransportResolution:

    def test_stdio_transport(self):
        transport = resolve_client_transport_for_uri("stdio://./my_policy.py")
        assert isinstance(transport, StdioClientTransport)

    def test_http_transport(self):
        transport = resolve_client_transport_for_uri("http://localhost:8080")
        assert isinstance(transport, HttpClientTransport)

    def test_https_transport(self):
        transport = resolve_client_transport_for_uri("https://policies.example.com")
        assert isinstance(transport, HttpClientTransport)

    def test_unknown_scheme_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            resolve_client_transport_for_uri("grpc://localhost:50051")


class TestPolicyClient:

    def test_client_creation(self):
        client = PolicyClient("stdio://./test.py")
        assert client.uri == "stdio://./test.py"
        assert client.is_connected is False
        assert client.manifest is None

    def test_client_has_serializers(self):
        client = PolicyClient("http://localhost:8080")
        assert client._event_serializer is not None
        assert client._manifest_serializer is not None
        assert client._verdict_serializer is not None


class TestExceptions:

    def test_policy_denied(self):
        verdict = Verdict.deny("not allowed")
        exc = PolicyDenied(verdict)
        assert exc.verdict is verdict
        assert str(exc) == "not allowed"

    def test_policy_denied_no_reasoning(self):
        verdict = Verdict(decision=Decision.DENY)
        exc = PolicyDenied(verdict)
        assert str(exc) == "Policy denied"

    def test_policy_escalation(self):
        verdict = Verdict.escalate(
            type="human_confirm",
            prompt="Please confirm",
        )
        exc = PolicyEscalation(verdict)
        assert exc.verdict is verdict
        assert str(exc) == "Please confirm"

    def test_policy_escalation_no_escalation(self):
        verdict = Verdict(decision=Decision.ESCALATE)
        exc = PolicyEscalation(verdict)
        assert str(exc) == "Escalation required"


class _RaisingTransport(BaseClientTransport):
    async def connect(self):
        return None

    async def evaluate(self, serialized_event):
        raise PolicyUnavailableError("HTTP 500")

    async def close(self):
        pass


class _EmptyTransport(BaseClientTransport):
    async def connect(self):
        return None

    async def evaluate(self, serialized_event):
        return []

    async def close(self):
        pass


def _output_event():
    return PolicyEventBuilder().build_from_evaluation_args(
        event_type=EventType.OUTPUT_PRE_SEND
    )


def _client_with(transport, fail_mode=FailMode.CLOSED):
    client = PolicyClient("stdio://./x.py", fail_mode=fail_mode)
    client._transport = transport
    client._is_connected = True
    return client


class TestPolicyClientFailClosed:

    def test_unavailable_denies_by_default(self):
        client = _client_with(_RaisingTransport())
        verdicts = asyncio.run(client.evaluate(_output_event()))
        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.DENY

    def test_unavailable_allows_when_fail_open(self):
        client = _client_with(_RaisingTransport(), fail_mode=FailMode.OPEN)
        verdicts = asyncio.run(client.evaluate(_output_event()))
        assert verdicts[0].decision == Decision.ALLOW

    def test_empty_response_is_not_a_failure(self):
        # A healthy server with no opinion returns []; the client must not
        # synthesize a verdict and must not deny. Composing an empty verdict
        # set is the composer's concern (WP-2), not the client's.
        client = _client_with(_EmptyTransport())
        verdicts = asyncio.run(client.evaluate(_output_event()))
        assert verdicts == []


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self._response = response

    def post(self, url, json=None):
        return self._response


class TestHttpTransportFailClosed:

    def test_non_200_raises_unavailable(self):
        transport = HttpClientTransport("http://x")
        transport._session = _FakeSession(_FakeResponse(500, {}))
        with pytest.raises(PolicyUnavailableError):
            asyncio.run(transport.evaluate({}))

    def test_not_connected_raises_unavailable(self):
        transport = HttpClientTransport("http://x")  # _session is None
        with pytest.raises(PolicyUnavailableError):
            asyncio.run(transport.evaluate({}))

    def test_200_returns_verdicts(self):
        transport = HttpClientTransport("http://x")
        transport._session = _FakeSession(
            _FakeResponse(200, {"verdicts": [{"decision": "deny"}]})
        )
        assert asyncio.run(transport.evaluate({})) == [{"decision": "deny"}]
