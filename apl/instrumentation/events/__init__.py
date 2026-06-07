"""
Lifecycle events as one declarative table instead of one class per event.

Every event used to be its own ~20-line subclass differing only in (a) which payload
fields it reads off the lifecycle context and (b) which context slot a modification
writes to. That was 13 near-identical files and, worse, 13 separate places that each
forgot ``Modification.operation`` (ENGINEERING_REVIEW §3.4, §4.1/§4.2). Both facts are
data, so they live in the ``_EVENT_SPECS`` table below; a single
:class:`RegisteredEvent` interprets a spec and routes every modification through the
shared operation dispatcher in :mod:`apl.modifications`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict

from apl.types import EventPayload, EventType, Message

from .base_event import BaseEvent, TargetAccessor

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext

# Shared accessors: which lifecycle-context slot each modification target reads/writes.
_MESSAGES = TargetAccessor(
    get=lambda c: c.apl_messages,
    set=lambda c, v: c.modify_request_messages(v),
)
_RESPONSE_TEXT = TargetAccessor(
    get=lambda c: c.response_text,
    set=lambda c, v: c.modify_response_text(v),
)
_TOOL_ARGS = TargetAccessor(
    get=lambda c: c.tool_args,
    set=lambda c, v: c.modify_tool_args(v),
)
_TOOL_RESULT = TargetAccessor(
    get=lambda c: c.tool_result,
    set=lambda c, v: c.modify_tool_result(v),
)
_PLAN = TargetAccessor(
    get=lambda c: c.proposed_plan,
    set=lambda c, v: c.modify_proposed_plan(v),
)
_HANDOFF = TargetAccessor(
    get=lambda c: c.handoff_payload,
    set=lambda c, v: c.modify_handoff_payload(v),
)


@dataclass(frozen=True)
class EventSpec:
    """
    Declarative description of one lifecycle event.

    - ``payload_fields`` maps an :class:`EventPayload` field name to a function that
      reads it from the lifecycle context.
    - ``target_setters`` maps a modification ``target`` to the accessor for the context
      slot it modifies.
    """

    event_type: EventType
    payload_fields: dict[str, Callable[[LifecycleContext], Any]] = field(
        default_factory=dict
    )
    target_setters: dict[str, TargetAccessor] = field(default_factory=dict)


class RegisteredEvent(BaseEvent):
    """A concrete :class:`BaseEvent` whose behaviour comes from an :class:`EventSpec`."""

    def __init__(self, spec: EventSpec) -> None:
        self._spec = spec

    @property
    def event_type(self) -> EventType:
        return self._spec.event_type

    def build_payload(self, context: LifecycleContext) -> EventPayload:
        return EventPayload(
            **{name: read(context) for name, read in self._spec.payload_fields.items()}
        )

    def target_accessors(self) -> dict[str, TargetAccessor]:
        return self._spec.target_setters


_EVENT_SPECS: tuple[EventSpec, ...] = (
    EventSpec(EventType.INPUT_RECEIVED, target_setters={"input": _MESSAGES}),
    EventSpec(EventType.INPUT_VALIDATED, target_setters={"input": _MESSAGES}),
    EventSpec(
        EventType.LLM_PRE_REQUEST,
        payload_fields={
            "llm_model": lambda c: c.model_name,
            "llm_prompt": lambda c: c.apl_messages,
        },
        target_setters={"llm_prompt": _MESSAGES},
    ),
    EventSpec(
        EventType.LLM_POST_RESPONSE,
        payload_fields={
            "llm_model": lambda c: c.model_name,
            "llm_response": lambda c: Message(
                role="assistant", content=c.response_text
            ),
        },
        target_setters={"output": _RESPONSE_TEXT},
    ),
    EventSpec(
        EventType.TOOL_PRE_INVOKE,
        payload_fields={
            "tool_name": lambda c: c.tool_name,
            "tool_args": lambda c: c.tool_args,
        },
        target_setters={"tool_args": _TOOL_ARGS},
    ),
    EventSpec(
        EventType.TOOL_POST_INVOKE,
        payload_fields={
            "tool_name": lambda c: c.tool_name,
            "tool_args": lambda c: c.tool_args,
            "tool_result": lambda c: c.tool_result,
        },
        target_setters={"tool_result": _TOOL_RESULT},
    ),
    EventSpec(
        EventType.OUTPUT_PRE_SEND,
        payload_fields={"output_text": lambda c: c.response_text},
        target_setters={"output": _RESPONSE_TEXT},
    ),
    EventSpec(EventType.SESSION_START),
    EventSpec(EventType.SESSION_END),
    EventSpec(
        EventType.PLAN_PROPOSED,
        payload_fields={"plan": lambda c: c.proposed_plan},
        target_setters={"plan": _PLAN},
    ),
    EventSpec(
        EventType.PLAN_APPROVED,
        payload_fields={"plan": lambda c: c.proposed_plan},
    ),
    EventSpec(
        EventType.AGENT_PRE_HANDOFF,
        payload_fields={
            "target_agent": lambda c: c.target_agent,
            "source_agent": lambda c: c.source_agent,
            "handoff_payload": lambda c: c.handoff_payload,
        },
        target_setters={"handoff_payload": _HANDOFF},
    ),
    EventSpec(
        EventType.AGENT_POST_HANDOFF,
        payload_fields={
            "target_agent": lambda c: c.target_agent,
            "source_agent": lambda c: c.source_agent,
            "handoff_payload": lambda c: c.handoff_payload,
        },
    ),
)

EVENT_REGISTRY: Dict[str, BaseEvent] = {
    spec.event_type.value: RegisteredEvent(spec) for spec in _EVENT_SPECS
}


def get_event(event_name: str) -> BaseEvent:
    return EVENT_REGISTRY[event_name]


__all__ = [
    "EVENT_REGISTRY",
    "BaseEvent",
    "EventSpec",
    "RegisteredEvent",
    "TargetAccessor",
    "get_event",
]
