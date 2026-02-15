from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..lifecycle.context import LifecycleContext
from ..lifecycle.sequence import EventSequence

if TYPE_CHECKING:
    from ..state import InstrumentationState


class BaseLifecycleExecutor(ABC):
    def __init__(self, state: "InstrumentationState"):
        self.state = state

    @abstractmethod
    def execute_sequence(
        self,
        sequence: EventSequence,
        context: LifecycleContext,
    ) -> None: ...
