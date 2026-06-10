from __future__ import annotations

import asyncio
import json
import sys

import pytest
from aiohttp.test_utils import TestClient, TestServer

from apl.server import PolicyServer
from apl.transports.http import create_http_application
from apl.transports.stdio import StdioTransport
from apl.types import EventType, PolicyEvent, PolicyUnavailableError


def _run(coro):
    return asyncio.run(coro)


def _valid_event_wire() -> dict:
    from apl.serialization import to_wire

    return to_wire(PolicyEvent(type=EventType.INPUT_RECEIVED))


# ===========================================================================
# stdio server: a malformed frame is skipped, not fatal
# ===========================================================================


class TestStdioServerResilience:
    def _consume(self, frames: bytes) -> str:
        """
        Run the read loop over ``frames`` and return everything written to stdout.
        """
        import io
        from contextlib import redirect_stdout

        transport = StdioTransport(PolicyServer("s"))

        async def run():
            # StreamReader must be constructed inside the running loop (3.12).
            reader = asyncio.StreamReader()
            reader.feed_data(frames)
            reader.feed_eof()
            await transport.consume(reader)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _run(run())
        return buffer.getvalue()

    def test_malformed_frame_does_not_kill_the_loop(self):
        # Pre-fix: json.loads ran *inside* the reader generator, so a bad frame
        # raised out of `async for` (past the unreachable handler) and the loop
        # died. A later valid ping must still be answered.
        out = self._consume(b'this is not json\n{"type":"ping"}\n')
        assert '"pong"' in out

    def test_non_object_frame_is_skipped(self):
        out = self._consume(b'[1, 2, 3]\n{"type":"ping"}\n')
        assert '"pong"' in out

    def test_handler_error_does_not_kill_the_loop(self):
        # A frame that blows up inside handling (bad event payload) is logged
        # and skipped; the next valid frame is still served.
        out = self._consume(
            b'{"type":"evaluate","event":{"type":"bogus"}}\n{"type":"ping"}\n'
        )
        assert '"pong"' in out


# ===========================================================================
# stdio client: timeouts, stderr drain, kill-escalation, fail-closed
# ===========================================================================


class _ScriptStdioClient:
    """
    A stdio client whose 'server' is an inline python script.

    Bypasses ``_build_spawn_args`` (naive shell split) so argv is passed cleanly; the
    connect/evaluate/timeout/drain/close logic under test is the real thing.
    """

    @staticmethod
    def make(script: str, **kwargs):
        from apl.layer.client_transports import StdioClientTransport

        class _Client(StdioClientTransport):
            def _build_spawn_args(self):
                return [sys.executable, "-c", script]

        return _Client("stdio://inline", **kwargs)


_MANIFEST = (
    "import sys\n"
    'sys.stdout.write(\'{"type":"manifest","manifest":{}}\\n\')\n'
    "sys.stdout.flush()\n"
)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess semantics")
class TestStdioClientReliability:
    def test_hung_server_times_out_instead_of_hanging(self):
        # Pre-fix: readline() had no timeout -> the caller hung forever.
        script = _MANIFEST + "import time\ntime.sleep(60)\n"
        client = _ScriptStdioClient.make(script, timeout_seconds=0.5)

        async def run():
            await client.connect()
            start = asyncio.get_event_loop().time()
            with pytest.raises(PolicyUnavailableError):
                await client.evaluate({"x": 1})
            elapsed = asyncio.get_event_loop().time() - start
            await client.close()
            return elapsed

        elapsed = _run(run())
        assert elapsed < 3.0  # bounded by the 0.5s timeout, not hung

    def test_evaluate_on_a_different_loop_fails_closed(self):
        # A subprocess transport can't move between loops; if connect() bound it
        # to one loop and evaluate() runs on another, fail closed with a clear
        # message rather than crash deep in asyncio.
        from apl.layer.client_transports import StdioClientTransport

        class _FakeProc:
            stdin = object()

        transport = StdioClientTransport("stdio://noop.py")
        transport._process = _FakeProc()
        other_loop = asyncio.new_event_loop()
        transport._bound_loop = other_loop  # "connected" on a different loop

        with pytest.raises(PolicyUnavailableError, match="different event loop"):
            _run(transport.evaluate({"x": 1}))
        other_loop.close()

    def test_no_response_fails_closed(self):
        # Server emits a manifest then exits without answering evaluate.
        # Pre-fix this raised ConnectionError, which PolicyClient does NOT catch
        # (it only catches PolicyUnavailableError) -> not fail-closed.
        client = _ScriptStdioClient.make(_MANIFEST, timeout_seconds=2.0)

        async def run():
            await client.connect()
            with pytest.raises(PolicyUnavailableError):
                await client.evaluate({"x": 1})
            await client.close()

        _run(run())

    def test_chatty_stderr_does_not_deadlock(self):
        # Server floods stderr (~200KB > pipe buffer) before answering. Pre-fix
        # stderr was never drained -> the server blocked on write while we
        # blocked on read -> deadlock. The drain task keeps both moving.
        script = _MANIFEST + (
            "import sys\n"
            "for _ in sys.stdin:\n"
            "    sys.stderr.write('X' * 200000); sys.stderr.flush()\n"
            "    sys.stdout.write('"
            '{"type":"verdicts","verdicts":[{"decision":"deny"}]}'
            "\\n'); sys.stdout.flush()\n"
        )
        client = _ScriptStdioClient.make(script, timeout_seconds=5.0)

        async def run():
            await client.connect()
            verdicts = await asyncio.wait_for(client.evaluate({"x": 1}), timeout=10)
            await client.close()
            return verdicts

        verdicts = _run(run())
        assert verdicts == [{"decision": "deny"}]

    def test_close_escalates_to_kill_when_sigterm_ignored(self, monkeypatch):
        # Pre-fix: close() did terminate() + unbounded wait() with no kill
        # escalation -> a server ignoring SIGTERM hung close() forever.
        from apl.layer.client_transports import stdio_client_transport

        monkeypatch.setattr(stdio_client_transport, "_TERMINATE_GRACE_SECONDS", 0.3)
        script = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            + _MANIFEST
            + "time.sleep(60)\n"
        )
        client = _ScriptStdioClient.make(script, timeout_seconds=2.0)

        async def run():
            await client.connect()
            proc = client._process
            await asyncio.wait_for(client.close(), timeout=5)
            return proc.returncode

        returncode = _run(run())
        assert returncode is not None  # process actually exited
        assert returncode == -9  # SIGKILL (escalated past the ignored SIGTERM)

    def test_close_before_connect_is_noop(self):
        client = _ScriptStdioClient.make(_MANIFEST)
        _run(client.close())  # must not raise


# ===========================================================================
# HTTP client: timeout wired, connect fails closed
# ===========================================================================


class _FakeAiohttpResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class _RecordingSession:
    last_timeout = None

    def __init__(self, *, timeout=None):
        type(self).last_timeout = timeout

    def get(self, url):
        return _FakeAiohttpResponse(200, {"server_name": "x", "policies": []})

    async def close(self):
        pass


class _FailingSession:
    def __init__(self, *, timeout=None):
        pass

    def get(self, url):
        return _FakeAiohttpResponse(500, {})

    async def close(self):
        pass


class TestHttpClientReliability:
    def test_connect_sets_a_client_timeout(self, monkeypatch):
        # Pre-fix: ClientSession() had no ClientTimeout (aiohttp's 5-minute
        # default) on the agent's hot path.
        import aiohttp

        from apl.layer.client_transports import HttpClientTransport

        monkeypatch.setattr(aiohttp, "ClientSession", _RecordingSession)
        transport = HttpClientTransport("http://x", timeout_seconds=2.5)
        _run(transport.connect())

        assert _RecordingSession.last_timeout is not None
        assert _RecordingSession.last_timeout.total == 2.5

    def test_connect_non_200_fails_closed(self, monkeypatch):
        # Pre-fix: a non-200 manifest raised ConnectionError, which the client
        # layer does not catch -> escapes the fail-closed path.
        import aiohttp

        from apl.layer.client_transports import HttpClientTransport

        monkeypatch.setattr(aiohttp, "ClientSession", _FailingSession)
        transport = HttpClientTransport("http://x")
        with pytest.raises(PolicyUnavailableError):
            _run(transport.connect())

    def test_session_recreated_when_loop_changes(self, monkeypatch):
        # aiohttp pins a session to its loop; if connect() ran on one loop and
        # evaluate() runs on another (eager connect, or the LangGraph sync
        # bridge), the transport must recreate the session, not crash on a
        # closed loop.
        import aiohttp

        from apl.layer.client_transports import HttpClientTransport

        class _Fake:
            closed = False

            def __init__(self, *, timeout=None):
                pass

            def get(self, url):
                return _FakeAiohttpResponse(200, {"server_name": "x", "policies": []})

            async def close(self):
                pass

        monkeypatch.setattr(aiohttp, "ClientSession", _Fake)
        transport = HttpClientTransport("http://x")

        loop_a = asyncio.new_event_loop()
        loop_a.run_until_complete(transport.connect())
        first = transport._session

        async def _resolve():
            return transport._session_for_current_loop()

        loop_b = asyncio.new_event_loop()
        second = loop_b.run_until_complete(_resolve())
        loop_a.close()
        loop_b.close()

        assert second is not first  # recreated for the new loop


# ===========================================================================
# HTTP server security & semantics
# ===========================================================================


async def _http(app, method, path, *, headers=None, json_body=None, data=None):
    """
    Drive one request against ``app`` and return primitives (the response object is
    closed before we return).
    """
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.request(
            method, path, headers=headers, json=json_body, data=data
        )
        text = await resp.text()
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        return {
            "status": resp.status,
            "headers": dict(resp.headers),
            "text": text,
            "json": body,
        }
    finally:
        await client.close()


class TestHttpRootRedirect:
    def test_root_redirects_to_health(self):
        # "/" must be served by a coroutine: aiohttp 3.x rejects the old sync lambda at
        # request time, so the redirect failed when actually hit (and nothing covered
        # it). Assert the 302 survives the full middleware stack.
        app = create_http_application(PolicyServer("t"))

        async def go():
            server = TestServer(app)
            client = TestClient(server)
            await client.start_server()
            try:
                resp = await client.request("GET", "/", allow_redirects=False)
                return resp.status, resp.headers.get("Location")
            finally:
                await client.close()

        status, location = _run(go())
        assert status == 302
        assert location == "/health"


class TestHttpInputValidation:
    def test_unknown_event_type_is_400_not_500(self):
        app = create_http_application(PolicyServer("t"))
        r = _run(_http(app, "POST", "/evaluate", json_body={"type": "totally_bogus"}))
        assert r["status"] == 400
        assert r["json"]["error"] == "invalid_request"

    def test_bad_input_does_not_echo_the_exception(self):
        # Pre-fix: ValueError from EventType(...) became a 500 echoing str(e).
        app = create_http_application(PolicyServer("t"))
        r = _run(_http(app, "POST", "/evaluate", json_body={"type": "totally_bogus"}))
        assert "totally_bogus" not in r["text"]
        assert "Traceback" not in r["text"]
        assert "ValidationError" not in r["text"]

    def test_wrong_content_type_is_415(self):
        app = create_http_application(PolicyServer("t"))
        r = _run(
            _http(
                app,
                "POST",
                "/evaluate",
                data="{}",
                headers={"Content-Type": "text/plain"},
            )
        )
        assert r["status"] == 415
        assert r["json"]["error"] == "unsupported_media_type"

    def test_malformed_json_is_400(self):
        app = create_http_application(PolicyServer("t"))
        r = _run(
            _http(
                app,
                "POST",
                "/evaluate",
                data="{ not json",
                headers={"Content-Type": "application/json"},
            )
        )
        assert r["status"] == 400
        assert r["json"]["error"] == "invalid_json"

    def test_oversize_body_is_413(self):
        app = create_http_application(PolicyServer("t"), max_request_bytes=64)
        big = {"type": "input.received", "padding": "x" * 500}
        r = _run(_http(app, "POST", "/evaluate", json_body=big))
        assert r["status"] == 413
        assert r["json"]["error"] == "payload_too_large"


class TestHttpRequestId:
    def test_request_id_present_on_error_path(self):
        # Pre-fix: request_id was the *innermost* middleware, so error responses
        # (produced by the outer error middleware) had no X-Request-ID.
        app = create_http_application(PolicyServer("t"))
        r = _run(
            _http(
                app,
                "POST",
                "/evaluate",
                data="{ bad",
                headers={"Content-Type": "application/json"},
            )
        )
        assert "X-Request-ID" in r["headers"]
        assert r["json"]["request_id"]

    def test_caller_request_id_is_echoed(self):
        app = create_http_application(PolicyServer("t"))
        r = _run(_http(app, "GET", "/health", headers={"X-Request-ID": "abc-123"}))
        assert r["headers"]["X-Request-ID"] == "abc-123"


class TestHttpCors:
    def test_no_cors_headers_by_default(self):
        # Pre-fix: CORS:* was stamped on every response unconditionally.
        app = create_http_application(PolicyServer("t"))
        r = _run(
            _http(app, "GET", "/health", headers={"Origin": "https://anything.example"})
        )
        assert "Access-Control-Allow-Origin" not in r["headers"]

    def test_allowed_origin_is_reflected(self):
        app = create_http_application(
            PolicyServer("t"), cors_origins=["https://ok.example"]
        )
        r = _run(_http(app, "GET", "/health", headers={"Origin": "https://ok.example"}))
        assert r["headers"]["Access-Control-Allow-Origin"] == "https://ok.example"

    def test_disallowed_origin_is_not_reflected(self):
        app = create_http_application(
            PolicyServer("t"), cors_origins=["https://ok.example"]
        )
        r = _run(
            _http(app, "GET", "/health", headers={"Origin": "https://evil.example"})
        )
        assert "Access-Control-Allow-Origin" not in r["headers"]


class TestHttpAuth:
    def test_protected_route_401_without_token(self):
        app = create_http_application(PolicyServer("t"), auth_token="secret")
        r = _run(_http(app, "POST", "/evaluate", json_body=_valid_event_wire()))
        assert r["status"] == 401
        assert r["json"]["error"] == "unauthorized"

    def test_protected_route_ok_with_token(self):
        app = create_http_application(PolicyServer("t"), auth_token="secret")
        r = _run(
            _http(
                app,
                "POST",
                "/evaluate",
                json_body=_valid_event_wire(),
                headers={"Authorization": "Bearer secret"},
            )
        )
        assert r["status"] == 200
        assert "composed_verdict" in r["json"]

    def test_health_is_public_even_with_auth(self):
        app = create_http_application(PolicyServer("t"), auth_token="secret")
        r = _run(_http(app, "GET", "/health"))
        assert r["status"] == 200

    def test_no_auth_required_when_unconfigured(self):
        app = create_http_application(PolicyServer("t"))
        r = _run(_http(app, "POST", "/evaluate", json_body=_valid_event_wire()))
        assert r["status"] == 200


# ===========================================================================
# port auto-kill removed; safe bind default
# ===========================================================================


class TestPortAutoKillRemoved:
    def test_utilities_package_is_gone(self):
        # The lsof + os.kill(SIGKILL) port grabber killed arbitrary unrelated
        # processes; it must not exist anymore.
        with pytest.raises(ModuleNotFoundError):
            __import__("apl.utilities")

    def test_http_transport_does_not_reference_kill(self):
        import inspect

        from apl.transports.http import http_transport

        source = inspect.getsource(http_transport)
        assert "kill_process_on_port" not in source
        assert "SIGKILL" not in source

    def test_http_transport_defaults_to_loopback(self):
        from apl.transports.http.http_transport import DEFAULT_HOST, HTTPTransport

        assert DEFAULT_HOST == "127.0.0.1"
        transport = HTTPTransport(PolicyServer("t"))
        assert transport._host == "127.0.0.1"
