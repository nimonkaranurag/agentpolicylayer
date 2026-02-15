from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class ToolPreInvokeEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.TOOL_PRE_INVOKE

    def build_payload(
        self, context: LifecycleContext
    ) -> EventPayload:
        return EventPayload(
            tool_name=context.tool_name,
            tool_args=context.tool_args,
        )

    def _apply_modification_for_target(
        self,
        target: str,
        value: Any,
        context: LifecycleContext,
    ) -> None:
        if target == "tool_args":
            context.modify_tool_args(value)
