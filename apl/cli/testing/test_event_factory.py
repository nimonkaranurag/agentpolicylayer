from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from ...types import (
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    SessionMetadata,
)
from .sample_payloads import SAMPLE_PAYLOADS_BY_EVENT_TYPE


class TestEventFactory:
    def build(
        self,
        event_type_str: str,
        payload_json: Optional[str] = None,
    ) -> PolicyEvent:
        payload = self._resolve_payload(
            event_type_str, payload_json
        )
        return PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType(event_type_str),
            timestamp=datetime.now(),
            messages=[
                Message(
                    role="user", content="Test message"
                )
            ],
            payload=payload,
            metadata=SessionMetadata(
                session_id="test-session",
                user_id="test-user",
                token_count=1000,
                token_budget=10000,
            ),
        )

    def _resolve_payload(
        self, event_type_str, payload_json
    ) -> EventPayload:
        if payload_json:
            return EventPayload(
                **json.loads(payload_json)
            )
        return SAMPLE_PAYLOADS_BY_EVENT_TYPE.get(
            event_type_str, EventPayload()
        )
