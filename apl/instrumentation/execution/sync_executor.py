from __future__ import annotations

from ..lifecycle.context import LifecycleContext
from ..lifecycle.sequence import EventSequence
from .base_executor import BaseLifecycleExecutor


class SyncLifecycleExecutor(BaseLifecycleExecutor):

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
