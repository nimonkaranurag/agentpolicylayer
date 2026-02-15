from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apl.types import EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class InputValidatedEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.INPUT_VALIDATED

    def _apply_modification_for_target(
        self,
        target: str,
        value: Any,
        context: LifecycleContext,
    ) -> None:
        if target == "input":
            context.modify_request_messages(value)
