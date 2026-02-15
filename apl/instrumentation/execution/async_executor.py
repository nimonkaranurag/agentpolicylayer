from __future__ import annotations

from ..lifecycle.context import LifecycleContext
from ..lifecycle.sequence import EventSequence
from .base_executor import BaseLifecycleExecutor


class AsyncLifecycleExecutor(BaseLifecycleExecutor):

    async def execute_sequence(
        self,
        sequence: EventSequence,
        context: LifecycleContext,
    ) -> None:
        for event in sequence:
            verdict = await self.policy_evaluator.evaluate_event_async(
                event, context
            )
            self.verdict_handler.raise_if_blocked(
                verdict, event.event_type.value
            )
            event.apply_verdict_modifications(
                verdict, context
            )
