from typing import TYPE_CHECKING

from apl.types import EventPayload, EventType

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class LLMPreRequestEvent(BaseEvent):
    @property
    def event_type(self) -> EventType:
        return EventType.LLM_PRE_REQUEST

    def build_payload(
        self, context: "LifecycleContext"
    ) -> EventPayload:
        return EventPayload(
            llm_model=context.model_name,
            llm_prompt=context.apl_messages,
        )

    def _apply_modification_for_target(
        self,
        target: str,
        value: any,
        context: "LifecycleContext",
    ) -> None:
        if target == "llm_prompt":
            context.modify_request_messages(value)
