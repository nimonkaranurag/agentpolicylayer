from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any

from .base_client_transport import BaseClientTransport

logger: logging.Logger = logging.getLogger("apl")


class StdioClientTransport(BaseClientTransport):

    def __init__(self, uri: str) -> None:
        self._raw_command: str = uri[len("stdio://") :]
        self._process: (
            asyncio.subprocess.Process | None
        ) = None

    async def connect(self) -> dict | None:
        args: list[str] = self._build_spawn_args()
        logger.info(f"Spawning policy server: {args}")

        self._process = (
            await asyncio.create_subprocess_exec(
                *args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )

        first_line: bytes = (
            await self._process.stdout.readline()
        )
        if not first_line:
            return None

        message: dict[str, Any] = json.loads(
            first_line.decode()
        )
        if message.get("type") == "manifest":
            return message.get("manifest", {})
        return None

    async def evaluate(
        self, serialized_event: dict
    ) -> list[dict]:
        if (
            self._process is None
            or self._process.stdin is None
        ):
            raise ConnectionError(
                "Policy server subprocess is not running"
            )

        wire_message: dict[str, Any] = {
            "type": "evaluate",
            "event": serialized_event,
        }

        line: str = json.dumps(wire_message) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

        response_line: bytes = (
            await self._process.stdout.readline()
        )
        if not response_line:
            raise ConnectionError(
                "Policy server subprocess returned no response"
            )

        response: dict[str, Any] = json.loads(
            response_line.decode()
        )
        if response.get("type") == "verdicts":
            return response.get("verdicts", [])

        logger.warning(
            f"Unexpected response type: {response.get('type')}"
        )
        return []

    async def close(self) -> None:
        if self._process is not None:
            self._process.terminate()
            await self._process.wait()
            self._process = None

    def _build_spawn_args(self) -> list[str]:
        command: str = self._raw_command
        if command.startswith("npx "):
            return command.split()
        if command.startswith("./"):
            return [sys.executable, command]
        return command.split()
