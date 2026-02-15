from __future__ import annotations

from apl.types import EventType

from .base_event import BaseEvent


class SessionEndEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.SESSION_END
