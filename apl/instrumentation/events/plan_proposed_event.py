from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class PlanProposedEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.PLAN_PROPOSED

    def build_payload(
        self, context: LifecycleContext
    ) -> EventPayload:
        return EventPayload(plan=context.proposed_plan)

    def _apply_modification_for_target(
        self,
        target: str,
        value: Any,
        context: LifecycleContext,
    ) -> None:
        if target == "plan":
            context.modify_proposed_plan(value)
