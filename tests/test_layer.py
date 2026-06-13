from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

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
from apl.layer.policy_layer import PolicyLayer
from apl.types import (
    CompositionConfig,
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

    def test_escalate_without_escalation_is_rejected(self):
        # Invariant: an ESCALATE verdict must carry an escalation, so the
        # "no escalation" state PolicyEscalation defends against can no longer be
        # constructed.
        with pytest.raises(ValidationError):
            Verdict(decision=Decision.ESCALATE)


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
        # set is the composer's concern, not the client's.
        client = _client_with(_EmptyTransport())
        verdicts = asyncio.run(client.evaluate(_output_event()))
        assert verdicts == []


class _FakeContent:
    """
    Minimal aiohttp StreamReader stand-in: read(n) returns up to n bytes.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self, n: int = -1) -> bytes:
        return self._data if n < 0 else self._data[:n]


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload
        # The transport now reads the body via response.content.read() to bound it,
        # so mirror aiohttp's StreamReader rather than only exposing .json().
        self.content = _FakeContent(json.dumps(payload).encode())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self._response = response

    def post(self, url, json=None, headers=None, allow_redirects=True):
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


# ---------------------------------------------------------------------------
# Layer-level timeout + fail-mode threading (apl/layer/policy_layer.py).
# Lives here with the other layer/client tests rather than in
# test_composition.py (which is strategy-only).
# ---------------------------------------------------------------------------


class _SlowClient:
    """
    A stand-in PolicyClient whose evaluate() outlives the layer timeout.
    """

    def __init__(self, delay: float) -> None:
        self._delay = delay

    async def evaluate(self, event):
        await asyncio.sleep(self._delay)
        return [Verdict.allow()]


class _InstantClient:
    def __init__(self, verdicts: list[Verdict]) -> None:
        self._verdicts = verdicts

    async def evaluate(self, event):
        return list(self._verdicts)


def _layer_with(clients, composition: CompositionConfig) -> PolicyLayer:
    layer = PolicyLayer(composition)
    layer._clients = list(clients)
    layer._is_connected = True  # skip connect(); fakes don't implement it
    return layer


class TestPolicyLayerTimeout:
    def test_timeout_denies_by_default(self):
        # on_timeout defaults to DENY: a hung server must fail closed.
        layer = _layer_with(
            [_SlowClient(1.0)],
            CompositionConfig(timeout_ms=10),
        )
        verdict = asyncio.run(layer.evaluate(EventType.OUTPUT_PRE_SEND))
        assert verdict.decision == Decision.DENY

    def test_timeout_allows_only_when_explicitly_configured(self):
        layer = _layer_with(
            [_SlowClient(1.0)],
            CompositionConfig(timeout_ms=10, on_timeout=Decision.ALLOW),
        )
        verdict = asyncio.run(layer.evaluate(EventType.OUTPUT_PRE_SEND))
        assert verdict.decision == Decision.ALLOW

    def test_fast_clients_compose_normally(self):
        # The timeout path must not disturb the normal composition path.
        layer = _layer_with(
            [_InstantClient([Verdict.deny("blocked")])],
            CompositionConfig(timeout_ms=500),
        )
        verdict = asyncio.run(layer.evaluate(EventType.OUTPUT_PRE_SEND))
        assert verdict.decision == Decision.DENY


class TestPolicyLayerFailModeThreading:
    def test_add_server_propagates_fail_mode(self):
        # Pre-fix the client always defaulted to CLOSED; the layer config never
        # reached it. Fails against pre-fix code.
        layer = PolicyLayer(CompositionConfig(fail_mode=FailMode.OPEN))
        layer.add_server("stdio://./x.py")
        assert layer._clients[0]._fail_mode == FailMode.OPEN

    def test_add_server_defaults_to_closed(self):
        layer = PolicyLayer()
        layer.add_server("stdio://./x.py")
        assert layer._clients[0]._fail_mode == FailMode.CLOSED


class TestEmptyLayerFailsClosed:
    # A PolicyLayer with no add_server() is a misconfiguration, not "all policies
    # abstained": composing zero verdicts used to silently ALLOW everything.

    def test_no_servers_denies_by_default(self):
        layer = PolicyLayer()
        verdict = asyncio.run(layer.evaluate(event_type=EventType.OUTPUT_PRE_SEND))
        assert verdict.decision == Decision.DENY

    def test_no_servers_allows_under_fail_open(self):
        layer = PolicyLayer(CompositionConfig(fail_mode=FailMode.OPEN))
        verdict = asyncio.run(layer.evaluate(event_type=EventType.OUTPUT_PRE_SEND))
        assert verdict.decision == Decision.ALLOW


class TestAddServerToken:
    def test_token_is_threaded_to_http_transport(self):
        layer = PolicyLayer()
        layer.add_server("http://policies.example", token="s3cret")
        transport = layer._clients[0]._transport
        assert transport._headers.get("Authorization") == "Bearer s3cret"
