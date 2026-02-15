import sys
from typing import TYPE_CHECKING

from apl.logging import get_logger
from apl.serialization import EventSerializer, ManifestSerializer, VerdictSerializer

from .message_writer import write_json_line

if TYPE_CHECKING:
    from apl.server import PolicyServer

logger = get_logger("transport.stdio")


class StdioProtocolHandler:
    def __init__(self, server: "PolicyServer"):
        self._server = server
        self._event_serializer = EventSerializer()
        self._verdict_serializer = VerdictSerializer()
        self._manifest_serializer = ManifestSerializer()

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
        event = self._event_serializer.deserialize(message.get("event", {}))
        verdicts = await self._server.evaluate(event)

        write_json_line({
            "type": "verdicts",
            "event_id": event.id,
            "verdicts": [self._verdict_serializer.serialize(v) for v in verdicts],
        })

    def _handle_ping(self) -> None:
        write_json_line({"type": "pong"})

    def _handle_shutdown(self) -> None:
        logger.info("Shutdown requested")
        sys.exit(0)

    def send_manifest(self) -> None:
        manifest = self._server.get_manifest()
        write_json_line({
            "type": "manifest",
            "manifest": self._manifest_serializer.serialize(manifest),
        })
