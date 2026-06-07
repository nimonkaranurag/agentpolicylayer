from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import sys
from typing import Any

from apl.types import PolicyUnavailableError

from .base_client_transport import BaseClientTransport

logger: logging.Logger = logging.getLogger("apl")

# Bounded waits so a hung policy server can never hang the agent's hot path. On
# any failure we raise PolicyUnavailableError (parity with the HTTP transport) so
# PolicyClient can fail closed.
DEFAULT_TIMEOUT_SECONDS: float = 10.0
# Grace period after SIGTERM before escalating to SIGKILL on our own child.
_TERMINATE_GRACE_SECONDS: float = 5.0


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

    async def connect(self) -> dict | None:
        args: list[str] = self._build_spawn_args()
        logger.info(f"Spawning policy server: {args}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            raise PolicyUnavailableError(
                f"could not spawn policy server {self._raw_command!r}: {exc}"
            ) from exc

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

        wire_message: dict[str, Any] = {
            "type": "evaluate",
            "event": serialized_event,
        }
        line: str = json.dumps(wire_message) + "\n"

        try:
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise PolicyUnavailableError(
                f"connection to policy server {self._raw_command!r} was lost: {exc}"
            ) from exc

        response_line = await self._read_line_or_unavailable("did not respond")
        if not response_line:
            raise PolicyUnavailableError(
                "policy server subprocess returned no response"
            )

        try:
            response: dict[str, Any] = json.loads(response_line.decode())
        except json.JSONDecodeError as exc:
            raise PolicyUnavailableError(
                f"policy server {self._raw_command!r} sent a malformed response"
            ) from exc

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
