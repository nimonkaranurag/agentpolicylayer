from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys
from typing import Any

from apl.logging import APLLogger, get_logger
from apl.types import PolicyUnavailableError

from .base_client_transport import BaseClientTransport

logger: APLLogger = get_logger("transport.stdio_client")

# Bounded waits so a hung policy server can never hang the agent's hot path. On
# any failure we raise PolicyUnavailableError (parity with the HTTP transport) so
# PolicyClient can fail closed.
DEFAULT_TIMEOUT_SECONDS: float = 10.0
# Grace period after SIGTERM before escalating to SIGKILL on our own child.
_TERMINATE_GRACE_SECONDS: float = 5.0
# Newline-delimited frames can legitimately be large (a big tool result). asyncio's
# StreamReader defaults to a 64 KiB line limit and raises an *uncaught*
# LimitOverrunError past it, which crashed the transport on a valid payload. Lift
# the subprocess pipe limit to a generous bound; anything still over it fails closed.
_MAX_FRAME_BYTES: int = 16 * 1024 * 1024  # 16 MiB

# Environment variable names whose values are secrets the *agent* holds (LLM API
# keys, cloud credentials, bearer tokens). A spawned stdio policy server is a
# separate — possibly third-party (`npx some-server`) — trust domain, so we strip
# these before handing it the environment rather than leaking the agent's keys.
_SENSITIVE_ENV_PATTERN = re.compile(
    r"(API_KEY|ACCESS_KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|_TOKEN|^TOKEN$)",
    re.IGNORECASE,
)


def _child_env() -> dict[str, str]:
    """
    The environment to hand a spawned stdio policy server.

    A copy of the parent environment with secret-looking variables removed, so an
    agent's LLM/cloud keys aren't exposed to policy code in a different trust domain.
    Non-secret config (PATH, HOME, locale, …) is preserved so the server still starts
    normally.
    """
    return {
        key: value
        for key, value in os.environ.items()
        if not _SENSITIVE_ENV_PATTERN.search(key)
    }


class StdioClientTransport(BaseClientTransport):
    def __init__(
        self,
        uri: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._raw_command: str = uri[len("stdio://") :]
        self._timeout_seconds: float = timeout_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_drain: asyncio.Task | None = None
        # One subprocess and one stdin/stdout pipe are shared by every concurrent
        # evaluate() on this transport, so the whole write→read round-trip must be
        # serialised: without this two requests interleave on the pipe and a call
        # can read a *sibling* event's verdict.
        self._io_lock: asyncio.Lock = asyncio.Lock()
        # The subprocess and its stream transports are bound to the loop they were
        # created on. We record it so evaluate() can fail closed with a clear
        # message if it runs on a different loop, rather than crash deep in asyncio.
        self._bound_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> dict | None:
        args: list[str] = self._build_spawn_args()
        logger.info(f"Spawning policy server: {args}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                limit=_MAX_FRAME_BYTES,
                env=_child_env(),
            )
        except (OSError, ValueError) as exc:
            raise PolicyUnavailableError(
                f"could not spawn policy server {self._raw_command!r}: {exc}"
            ) from exc

        self._bound_loop = asyncio.get_running_loop()

        # Drain stderr continuously: an undrained PIPE fills (~64KB) and the
        # server deadlocks waiting to write while we wait to read stdout.
        self._stderr_drain = asyncio.ensure_future(self._drain_stderr())

        first_line = await self._read_line_or_unavailable("did not send a manifest")
        if not first_line:
            await self._terminate_process()
            return None

        try:
            message: dict[str, Any] = json.loads(first_line.decode())
        except json.JSONDecodeError as exc:
            await self._terminate_process()
            raise PolicyUnavailableError(
                f"policy server {self._raw_command!r} sent a malformed manifest"
            ) from exc

        if message.get("type") == "manifest":
            return message.get("manifest", {})
        return None

    async def evaluate(self, serialized_event: dict) -> list[dict]:
        if self._process is None or self._process.stdin is None:
            raise PolicyUnavailableError("policy server subprocess is not running")

        if self._bound_loop is not asyncio.get_running_loop():
            raise PolicyUnavailableError(
                f"stdio policy server {self._raw_command!r} was connected on a "
                "different event loop; a subprocess transport can't move between "
                "loops. Connect and evaluate on the same loop (don't mix a sync "
                "graph.invoke with async ainvoke on one layer), or use the HTTP "
                "transport."
            )

        event_id = serialized_event.get("id")
        wire_message: dict[str, Any] = {
            "type": "evaluate",
            "event": serialized_event,
        }
        line: str = json.dumps(wire_message) + "\n"

        # Serialise the entire write→read round-trip: concurrent evaluate() calls
        # over the single pipe would otherwise interleave and cross verdicts.
        async with self._io_lock:
            try:
                try:
                    self._process.stdin.write(line.encode())
                    await self._process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError) as exc:
                    raise PolicyUnavailableError(
                        f"connection to policy server {self._raw_command!r} was "
                        f"lost: {exc}"
                    ) from exc

                response_line = await self._read_line_or_unavailable("did not respond")
            except asyncio.CancelledError:
                # A layer-level timeout cancelled us mid-round-trip. The request was
                # already written, so its reply is still in flight; reusing this
                # subprocess would hand that reply to the *next* event (a permanent
                # off-by-one). Tear it down so the next evaluate reconnects clean.
                await self._terminate_process()
                raise

            if not response_line:
                raise PolicyUnavailableError(
                    "policy server subprocess returned no response"
                )

            try:
                response: dict[str, Any] = json.loads(response_line.decode())
            except json.JSONDecodeError as exc:
                await self._terminate_process()
                raise PolicyUnavailableError(
                    f"policy server {self._raw_command!r} sent a malformed response"
                ) from exc

            # Correlate the reply with the request. The server stamps the event_id
            # it answered; a mismatch means the pipe desynced (e.g. a stale reply
            # left over from a cancelled call), so the verdict can't be trusted —
            # tear the subprocess down and fail closed rather than enforce the
            # wrong event's decision.
            response_event_id = response.get("event_id")
            if event_id is not None and response_event_id != event_id:
                await self._terminate_process()
                raise PolicyUnavailableError(
                    f"policy server {self._raw_command!r} answered event "
                    f"{response_event_id!r} for request {event_id!r}; the stdio "
                    f"pipe is desynchronised"
                )

            if response.get("type") == "verdicts":
                return response.get("verdicts", [])

        logger.warning(f"Unexpected response type: {response.get('type')}")
        return []

    async def close(self) -> None:
        await self._terminate_process()

    async def _read_line_or_unavailable(self, what: str) -> bytes:
        """
        Read one line from the server's stdout under the configured timeout.

        Raises PolicyUnavailableError on timeout so a hung server fails closed instead
        of hanging the caller forever.
        """
        assert self._process is not None and self._process.stdout is not None
        try:
            return await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            await self._terminate_process()
            raise PolicyUnavailableError(
                f"policy server {self._raw_command!r} {what} within "
                f"{self._timeout_seconds}s"
            ) from exc
        except (asyncio.LimitOverrunError, ValueError) as exc:
            # A single frame exceeded _MAX_FRAME_BYTES. Don't let the uncaught
            # error escape and crash the agent's hot path — tear the subprocess
            # down and fail closed.
            await self._terminate_process()
            raise PolicyUnavailableError(
                f"policy server {self._raw_command!r} sent a frame larger than "
                f"{_MAX_FRAME_BYTES} bytes"
            ) from exc

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                logger.debug(
                    f"[policy server stderr] {line.decode(errors='replace').rstrip()}"
                )
        except asyncio.CancelledError:
            # Expected: the drain task is cancelled when the subprocess is torn down.
            pass
        except Exception:
            # Draining is best-effort diagnostics; never let it surface.
            pass

    async def _terminate_process(self) -> None:
        drain, self._stderr_drain = self._stderr_drain, None
        if drain is not None:
            drain.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain

        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return

        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        except asyncio.TimeoutError:
            # Our own unresponsive child: escalate SIGTERM -> SIGKILL.
            process.kill()
            await process.wait()

    def _build_spawn_args(self) -> list[str]:
        command: str = self._raw_command
        if command.startswith("npx "):
            return command.split()
        if command.startswith("./"):
            return [sys.executable, command]
        return command.split()
