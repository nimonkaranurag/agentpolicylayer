from __future__ import annotations

from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
)

from apl.modifications import Accessor, apply_modifications
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

                new_args, new_kwargs = self._enforce_verdict(verdict, args, kwargs)
                return await func(*new_args, **new_kwargs)

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
    def _enforce_verdict(
        verdict: Any,
        positional_args: tuple[Any, ...],
        keyword_args: dict[str, Any],
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        Enforce the verdict and return the (possibly modified) call arguments.

        A MODIFY is written back to wherever ``tool_args`` actually came from — the
        ``tool_args`` *keyword* or the second *positional* argument (the README's own
        ``call_tool("name", {...})`` style). Writing only to ``kwargs`` while the value
        arrived positionally produced ``func(args..., tool_args=...)`` → ``TypeError:
        multiple values for argument 'tool_args'``.
        """
        if verdict.decision == Decision.DENY:
            raise PolicyDenied(verdict)

        if verdict.decision == Decision.ESCALATE:
            raise PolicyEscalation(verdict)

        if verdict.decision != Decision.MODIFY:
            return positional_args, keyword_args

        args = list(positional_args)
        kwargs = dict(keyword_args)
        # tool_name is positional[0], tool_args positional[1] (or the kwarg).
        in_kwargs = "tool_args" in kwargs
        in_positional = len(args) >= 2

        def resolve(target: str) -> Accessor | None:
            # The decorator runs *before* the wrapped call, so the only input it can
            # modify is tool_args. Any other target is refused loudly (fail closed)
            # via the shared applier rather than silently dropped.
            if target != "tool_args":
                return None

            def read_current() -> Any:
                if in_kwargs:
                    return kwargs.get("tool_args")
                if in_positional:
                    return args[1]
                return None

            def write_new(value: Any) -> None:
                if in_positional and not in_kwargs:
                    args[1] = value
                else:
                    kwargs["tool_args"] = value

            return read_current, write_new

        apply_modifications(verdict.modifications, resolve)
        return tuple(args), kwargs
