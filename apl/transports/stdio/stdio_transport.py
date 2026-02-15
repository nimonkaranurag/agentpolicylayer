import asyncio
import json
from typing import TYPE_CHECKING

from apl.logging import get_logger
from apl.transports.base_transport import BaseTransport

from .message_reader import (
    create_stdin_reader,
    read_json_lines,
)
from .protocol_handler import StdioProtocolHandler

if TYPE_CHECKING:
    from apl.server import PolicyServer

logger = get_logger("transport.stdio")


class StdioTransport(BaseTransport):
    def __init__(self, server: "PolicyServer"):
        super().__init__(server)
        self._running = False
        self._protocol_handler = StdioProtocolHandler(
            server
        )

    def run(self) -> None:
        asyncio.run(self._run_message_loop())

    async def start(self) -> None:
        self._running = True
        logger.info(
            f"APL Policy Server '{self.server.name}' starting on stdio..."
        )
        self._protocol_handler.send_manifest()

    async def stop(self) -> None:
        self._running = False

    async def _run_message_loop(self) -> None:
        await self.start()

        reader = await create_stdin_reader()

        async for message in read_json_lines(reader):
            try:
                await self._protocol_handler.handle_message(
                    message
                )
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
            except Exception as e:
                logger.error(f"Error handling message: {e}")

        await self.stop()
