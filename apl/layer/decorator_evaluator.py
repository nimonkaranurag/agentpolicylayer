from __future__ import annotations

from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
)

from apl.modifications import apply_operation
from apl.types import (
    Decision,
    EventPayload,
)

from .exceptions import PolicyDenied, PolicyEscalation

if TYPE_CHECKING:
    from .policy_layer import PolicyLayer


class PolicyDecoratorFactory:
    def __init__(self, policy_layer: PolicyLayer) -> None:
        self._policy_layer: PolicyLayer = policy_layer

    def create_event_decorator(
        self,
        event_type: str,
        messages_from: Callable[[], list] | None = None,
    ) -> Callable:

        def decorator(
            func: Callable[..., Coroutine],
        ) -> Callable[..., Coroutine]:

            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                payload: EventPayload = self._extract_payload_from_call_args(
                    args, kwargs
                )
                messages: list = messages_from() if messages_from else []

                verdict = await self._policy_layer.evaluate(
                    event_type=event_type,
                    messages=messages,
                    payload=payload,
                )

                self._enforce_verdict(verdict, kwargs)
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    @staticmethod
    def _extract_payload_from_call_args(
        positional_args: tuple[Any, ...],
        keyword_args: dict[str, Any],
    ) -> EventPayload:
        payload: EventPayload = EventPayload()

        if "tool_name" in keyword_args:
            payload.tool_name = keyword_args["tool_name"]
        if "tool_args" in keyword_args:
            payload.tool_args = keyword_args["tool_args"]
        if len(positional_args) >= 1:
            payload.tool_name = positional_args[0]
        if len(positional_args) >= 2:
            payload.tool_args = positional_args[1]

        return payload

    @staticmethod
    def _enforce_verdict(verdict: Any, keyword_args: dict[str, Any]) -> None:
        if verdict.decision == Decision.DENY:
            raise PolicyDenied(verdict)

        if verdict.decision == Decision.ESCALATE:
            raise PolicyEscalation(verdict)

        if verdict.decision == Decision.MODIFY:
            for modification in verdict.modifications:
                # The decorator runs *before* the wrapped call, so the only thing it can
                # modify is the call's inputs (tool_args). All operations are honoured
                # via the shared dispatcher; other targets are refused loudly rather
                # than silently dropped.
                if modification.target != "tool_args":
                    raise NotImplementedError(
                        "The policy decorator can only modify 'tool_args' before the "
                        f"call; got target={modification.target!r}"
                    )
                keyword_args["tool_args"] = apply_operation(
                    keyword_args.get("tool_args"), modification
                )
