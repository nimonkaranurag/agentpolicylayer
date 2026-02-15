from typing import TYPE_CHECKING

from ..evaluation import PolicyEvaluator, VerdictHandler
from ..lifecycle.context import LifecycleContext
from ..lifecycle.sequence import EventSequence
from .base_executor import BaseLifecycleExecutor

if TYPE_CHECKING:
    from ..state import InstrumentationState


class SyncLifecycleExecutor(BaseLifecycleExecutor):
    def __init__(self, state: "InstrumentationState"):
        super().__init__(state)
        self.policy_evaluator = PolicyEvaluator(state)
        self.verdict_handler = VerdictHandler()

    def execute_sequence(
        self,
        sequence: EventSequence,
        context: LifecycleContext,
    ) -> None:
        for event in sequence:
            verdict = (
                self.policy_evaluator.evaluate_event_sync(
                    event, context
                )
            )
            self.verdict_handler.raise_if_blocked(
                verdict, event.event_type.value
            )
            event.apply_verdict_modifications(
                verdict, context
            )
