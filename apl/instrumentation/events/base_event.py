from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Verdict,
)

if TYPE_CHECKING:
    from ..lifecycle.context import LifecycleContext


class BaseEvent(ABC):
    @property
    @abstractmethod
    def event_type(self) -> EventType: ...

    @abstractmethod
    def build_payload(
        self, context: "LifecycleContext"
    ) -> EventPayload: ...

    def apply_verdict_modifications(
        self, verdict: Verdict, context: "LifecycleContext"
    ) -> None:
        if verdict.decision != Decision.MODIFY:
            return

        if verdict.modification is None:
            return

        modification_target = verdict.modification.target
        modification_value = verdict.modification.value

        self._apply_modification_for_target(
            modification_target,
            modification_value,
            context,
        )

    def _apply_modification_for_target(
        self,
        target: str,
        value: any,
        context: "LifecycleContext",
    ) -> None:
        pass
