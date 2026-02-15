from typing import TYPE_CHECKING

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class InputReceivedEvent(BaseEvent):
    @property
    def event_type(self) -> EventType:
        return EventType.INPUT_RECEIVED

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
        if target == "input":
            context.modify_request_messages(value)
