from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apl.types import EventPayload, EventType, Message

from .base_event import BaseEvent

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class LLMPostResponseEvent(BaseEvent):

    @property
    def event_type(self) -> EventType:
        return EventType.LLM_POST_RESPONSE

    def build_payload(
        self, context: LifecycleContext
    ) -> EventPayload:
        return EventPayload(
            llm_model=context.model_name,
            llm_response=Message(
                role="assistant",
                content=context.response_text,
            ),
        )

    def _apply_modification_for_target(
        self,
        target: str,
        value: Any,
        context: LifecycleContext,
    ) -> None:
        if target == "output":
            context.modify_response_text(value)
