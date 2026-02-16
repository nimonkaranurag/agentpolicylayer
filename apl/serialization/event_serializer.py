import uuid
from datetime import datetime, timezone
from typing import Any

from apl.types import EventType, PolicyEvent

from .message_serializer import MessageSerializer
from .metadata_serializer import MetadataSerializer
from .payload_serializer import PayloadSerializer


class EventSerializer:
    def __init__(self):
        self._message_serializer = MessageSerializer()
        self._payload_serializer = PayloadSerializer(
            self._message_serializer
        )
        self._metadata_serializer = (
            MetadataSerializer()
        )

    def serialize(
        self, event: PolicyEvent
    ) -> dict[str, Any]:
        return {
            "id": event.id,
            "type": event.type.value,
            "timestamp": event.timestamp.isoformat(),
            "messages": [
                self._message_serializer.serialize(m)
                for m in event.messages
            ],
            "payload": self._payload_serializer.serialize(
                event.payload
            ),
            "metadata": self._metadata_serializer.serialize(
                event.metadata
            ),
        }

    def deserialize(
        self, data: dict[str, Any]
    ) -> PolicyEvent:
        return PolicyEvent(
            id=data.get("id", str(uuid.uuid4())),
            type=EventType(
                data.get("type", "input.received")
            ),
            timestamp=self._parse_timestamp(
                data.get("timestamp")
            ),
            messages=[
                self._message_serializer.deserialize(m)
                for m in data.get("messages", [])
            ],
            payload=self._payload_serializer.deserialize(
                data.get("payload", {})
            ),
            metadata=self._metadata_serializer.deserialize(
                data.get("metadata", {})
            ),
        )

    def _parse_timestamp(
        self, value: str | None
    ) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
