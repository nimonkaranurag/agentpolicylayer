from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apl.types import (
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    SessionMetadata,
)


class PolicyEventBuilder:

    def build_from_evaluation_args(
        self,
        event_type: EventType | str,
        messages: list[Message] | None = None,
        payload: EventPayload | None = None,
        metadata: SessionMetadata | None = None,
    ) -> PolicyEvent:
        normalized_event_type: EventType = (
            self._normalize_event_type(event_type)
        )
        resolved_metadata: SessionMetadata = (
            metadata
            or SessionMetadata(
                session_id=str(uuid.uuid4())
            )
        )

        return PolicyEvent(
            id=str(uuid.uuid4()),
            type=normalized_event_type,
            timestamp=datetime.now(timezone.utc),
            messages=messages or [],
            payload=payload or EventPayload(),
            metadata=resolved_metadata,
        )

    @staticmethod
    def _normalize_event_type(
        event_type: EventType | str,
    ) -> EventType:
        if isinstance(event_type, str):
            return EventType(event_type)
        return event_type
