from functools import wraps
from typing import TYPE_CHECKING

from apl.types import (
    ContextRequirement,
    EventType,
    PolicyEvent,
    Verdict,
)

from .registered_policy import (
    PolicyHandler,
    RegisteredPolicy,
)

if TYPE_CHECKING:
    from .policy_registry import PolicyRegistry


def create_policy_decorator(
    registry: "PolicyRegistry",
    policy_name: str,
    events: list[str],
    version: str = "1.0.0",
    context: list[str] | None = None,
    blocking: bool = True,
    timeout_ms: int = 1000,
    description: str | None = None,
):
    event_types = _parse_event_types(events)
    context_requirements = _parse_context_requirements(
        context
    )

    def decorator(handler: PolicyHandler) -> PolicyHandler:
        registered = RegisteredPolicy(
            name=policy_name,
            version=version,
            handler=handler,
            events=event_types,
            context_requirements=context_requirements,
            blocking=blocking,
            timeout_ms=timeout_ms,
            description=description,
        )

        registry.register(registered)

        @wraps(handler)
        async def wrapper(event: PolicyEvent) -> Verdict:
            from .handler_invoker import (
                invoke_policy_handler,
            )

            return await invoke_policy_handler(
                registered, event
            )

        return wrapper

    return decorator


def _parse_event_types(
    events: list[str | EventType],
) -> list[EventType]:
    result = []
    for event in events:
        if isinstance(event, EventType):
            result.append(event)
        else:
            try:
                result.append(EventType(event))
            except ValueError:
                raise ValueError(
                    f"Unknown event type: {event}"
                )
    return result


def _parse_context_requirements(
    context: list[str | ContextRequirement] | None,
) -> list[ContextRequirement]:
    if context is None:
        return []

    result = []
    for item in context:
        if isinstance(item, ContextRequirement):
            result.append(item)
        else:
            result.append(ContextRequirement(path=item))
    return result
