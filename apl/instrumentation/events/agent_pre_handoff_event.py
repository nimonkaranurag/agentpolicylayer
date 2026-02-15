from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class AgentPreHandoffEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.AGENT_PRE_HANDOFF

    def build_payload(
        self, context: LifecycleContext
    ) -> EventPayload:
        return EventPayload(
            target_agent=context.target_agent,
            source_agent=context.source_agent,
            handoff_payload=context.handoff_payload,
        )

    def _apply_modification_for_target(
        self,
        target: str,
        value: Any,
        context: LifecycleContext,
    ) -> None:
        if target == "handoff_payload":
            context.modify_handoff_payload(value)
