from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..evaluation import PolicyEvaluator, VerdictHandler
from ..lifecycle.context import LifecycleContext
from ..lifecycle.sequence import EventSequence

if TYPE_CHECKING:
    from ..state import InstrumentationState


class BaseLifecycleExecutor(ABC):

    def __init__(self, state: InstrumentationState) -> None:
        self.state: InstrumentationState = state
        self.policy_evaluator: PolicyEvaluator = (
            PolicyEvaluator(state)
        )
        self.verdict_handler: VerdictHandler = (
            VerdictHandler()
        )

    @abstractmethod
    def execute_sequence(
        self,
        sequence: EventSequence,
        context: LifecycleContext,
    ) -> None: ...
