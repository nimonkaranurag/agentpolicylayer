from typing import TYPE_CHECKING

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class SessionStartEvent(BaseEvent):
    @property
    def event_type(self) -> EventType:
        return EventType.SESSION_START

    def build_payload(
        self, context: "LifecycleContext"
    ) -> EventPayload:
        return EventPayload()

    def _apply_modification_for_target(
        self,
        target: str,
        value: any,
        context: "LifecycleContext",
    ) -> None:
        pass
