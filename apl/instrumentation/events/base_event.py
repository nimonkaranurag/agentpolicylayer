from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from apl.modifications import Accessor, apply_modifications
from apl.types import Decision, EventPayload, EventType, Verdict

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


@dataclass(frozen=True)
class TargetAccessor:
    """
    How to read and write one modifiable slot on the lifecycle context.

    A modification's ``operation`` (append/prepend/redact/patch) needs the *current*
    value, so an accessor pairs a getter with a setter rather than only a setter.
    """

    get: Callable[[LifecycleContext], Any]
    set: Callable[[LifecycleContext, Any], None]


class BaseEvent(ABC):
    """
    A lifecycle event: it knows its :class:`EventType`, can build the payload policies
    see, and can apply a MODIFY verdict back onto the lifecycle context.

    Concrete behaviour is data, not code: subclasses (in practice the single
    :class:`~apl.instrumentation.events.RegisteredEvent`) supply ``build_payload`` and
    ``target_accessors`` from a declarative table. The MODIFY-application algorithm lives
    here once and routes every modification through the shared operation dispatcher.
    """

    @property
    @abstractmethod
    def event_type(self) -> EventType: ...

    def build_payload(self, context: LifecycleContext) -> EventPayload:
        return EventPayload()

    def target_accessors(self) -> dict[str, TargetAccessor]:
        """
        Modification targets this event understands.

        Default: none.
        """
        return {}

    def apply_verdict_modifications(
        self,
        verdict: Verdict,
        context: LifecycleContext,
    ) -> None:
        """
        Apply a MODIFY verdict's modifications to the lifecycle context.

        Routed through the shared :func:`apply_modifications`, so a modification
        targeting a slot this event doesn't have (e.g. ``output`` at
        ``tool.pre_invoke``) raises :class:`UnsupportedModificationTarget` and the
        action is blocked — it is *not* silently skipped while the action proceeds
        unmodified, which was a fail-open (the policy demanded a change that never
        happened).
        """
        if verdict.decision != Decision.MODIFY:
            return

        accessors = self.target_accessors()

        def resolve(target: str) -> Accessor | None:
            accessor = accessors.get(target)
            if accessor is None:
                return None
            return (
                lambda: accessor.get(context),
                lambda value: accessor.set(context, value),
            )

        apply_modifications(verdict.modifications, resolve)
