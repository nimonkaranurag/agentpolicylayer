from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class OutputPreSendEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.OUTPUT_PRE_SEND

    def build_payload(
        self, context: LifecycleContext
    ) -> EventPayload:
        return EventPayload(
            output_text=context.response_text
        )

    def _apply_modification_for_target(
        self,
        target: str,
        value: Any,
        context: LifecycleContext,
    ) -> None:
        if target == "output":
            context.modify_response_text(value)
