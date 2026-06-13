"""
Stdio policy-server transport.

A newline-delimited JSON protocol spoken over stdin/stdout: the server emits a
``manifest`` frame on startup, then answers ``evaluate``/``ping``/``shutdown`` frames.
Reading and parsing are deliberately separated so a single malformed frame is *skipped*
(logged) rather than tearing down the read loop — for a guardrails product, one bad byte
must never silently stop enforcement.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any, AsyncIterator

from apl.logging import get_logger
from apl.serialization import event_from_wire, to_wire
from apl.transports.base_transport import BaseTransport

if TYPE_CHECKING:
    from apl.server import PolicyServer

logger = get_logger("transport.stdio")

# Match the client transport: asyncio's StreamReader defaults to a 64 KiB line
# limit and raises an uncaught LimitOverrunError past it, so a legitimately large
# event frame crashed the read loop. Lift the ceiling to a generous bound.
_MAX_FRAME_BYTES: int = 16 * 1024 * 1024  # 16 MiB


def write_json_line(message: dict[str, Any]) -> None:
    """
    Write one newline-delimited JSON message to stdout and flush.
    """
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


async def create_stdin_reader() -> asyncio.StreamReader:
    """
    Wrap the process stdin in an :class:`asyncio.StreamReader`.
    """
    reader = asyncio.StreamReader(limit=_MAX_FRAME_BYTES)
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    return reader


async def read_raw_lines(reader: asyncio.StreamReader) -> AsyncIterator[str]:
    """
    Yield decoded lines from ``reader`` until EOF.

    JSON parsing is intentionally left to the caller: a malformed frame must be
    skippable without raising out of the iterator (which would stop the read
    loop permanently). Undecodable bytes are replaced rather than raising.
    """
    while True:
        try:
            line = await reader.readline()
        except (asyncio.LimitOverrunError, ValueError) as exc:
            # A frame exceeded _MAX_FRAME_BYTES. We can't reliably resync the byte
            # stream past an unterminated oversize line, so stop the loop cleanly
            # with a clear log instead of letting an uncaught LimitOverrunError
            # tear the server down — the client's evaluate() then fails closed.
            logger.error(f"Oversize stdio frame (> {_MAX_FRAME_BYTES} bytes): {exc}")
            break
        if not line:
            break
        yield line.decode(errors="replace")


class StdioProtocolHandler:
    """
    Dispatches a parsed stdio frame to the policy server and writes the reply.
    """

    def __init__(self, server: "PolicyServer") -> None:
        self._server = server

    async def handle_message(self, message: dict) -> None:
        message_type = message.get("type")

        if message_type == "evaluate":
            await self._handle_evaluate(message)
        elif message_type == "ping":
            self._handle_ping()
        elif message_type == "shutdown":
            self._handle_shutdown()
        else:
            logger.warning(f"Unknown message type: {message_type}")

    async def _handle_evaluate(self, message: dict) -> None:
        event = event_from_wire(message.get("event", {}))
        verdicts = await self._server.evaluate(event)

        write_json_line(
            {
                "type": "verdicts",
                "event_id": event.id,
                "verdicts": [to_wire(v) for v in verdicts],
            }
        )

    def _handle_ping(self) -> None:
        write_json_line({"type": "pong"})

    def _handle_shutdown(self) -> None:
        logger.info("Shutdown requested")
        sys.exit(0)

    def send_manifest(self) -> None:
        manifest = self._server.get_manifest()
        write_json_line({"type": "manifest", "manifest": to_wire(manifest)})


class StdioTransport(BaseTransport):
    def __init__(self, server: "PolicyServer") -> None:
        super().__init__(server)
        self._running = False
        self._protocol_handler = StdioProtocolHandler(server)

    def run(self) -> None:
        asyncio.run(self._run_message_loop())

    async def start(self) -> None:
        self._running = True
        logger.info(f"APL Policy Server '{self.server.name}' starting on stdio...")
        self._protocol_handler.send_manifest()

    async def stop(self) -> None:
        self._running = False

    async def _run_message_loop(self) -> None:
        await self.start()
        reader = await create_stdin_reader()
        await self.consume(reader)
        await self.stop()

    async def consume(self, reader: asyncio.StreamReader) -> None:
        """
        Read and dispatch frames from ``reader`` until EOF.

        Each frame is isolated: a malformed or failing frame is logged and
        skipped so the loop keeps serving subsequent frames.
        """

        async for line in read_raw_lines(reader):
            await self._dispatch_line(line)

    async def _dispatch_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return

        try:
            message = json.loads(stripped)
        except json.JSONDecodeError as exc:
            logger.error(f"Skipping malformed JSON frame: {exc}")
            return

        if not isinstance(message, dict):
            logger.error(f"Skipping non-object frame: {type(message).__name__}")
            return

        try:
            await self._protocol_handler.handle_message(message)
        except Exception as exc:
            # One bad message must not kill the loop (DoS via a single frame).
            logger.error(f"Error handling message: {exc}")
