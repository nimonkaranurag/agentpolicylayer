from __future__ import annotations

from typing import TYPE_CHECKING

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class PlanApprovedEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.PLAN_APPROVED

    def build_payload(
        self, context: LifecycleContext
    ) -> EventPayload:
        return EventPayload(plan=context.proposed_plan)
