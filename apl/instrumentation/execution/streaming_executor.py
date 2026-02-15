from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Iterator,
)

from ..evaluation import PolicyEvaluator, VerdictHandler
from ..lifecycle.context import LifecycleContext
from ..lifecycle.sequence import EventSequence
from .base_executor import BaseLifecycleExecutor

if TYPE_CHECKING:
    from ..state import InstrumentationState


class StreamingLifecycleExecutor(BaseLifecycleExecutor):
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

    def wrap_sync_stream(
        self,
        stream: Iterator[Any],
        post_sequence: EventSequence,
        context: LifecycleContext,
        chunk_text_extractor: callable,
    ) -> Iterator[Any]:
        accumulated_text = ""

        for chunk in stream:
            chunk_text = chunk_text_extractor(chunk)
            accumulated_text += chunk_text
            yield chunk

        context.response_text = accumulated_text
        self.execute_sequence(post_sequence, context)

    async def wrap_async_stream(
        self,
        stream: AsyncIterator[Any],
        post_sequence: EventSequence,
        context: LifecycleContext,
        chunk_text_extractor: callable,
    ) -> AsyncIterator[Any]:
        accumulated_text = ""

        async for chunk in stream:
            chunk_text = chunk_text_extractor(chunk)
            accumulated_text += chunk_text
            yield chunk

        context.response_text = accumulated_text
        for event in post_sequence:
            verdict = await self.policy_evaluator.evaluate_event_async(
                event, context
            )
            self.verdict_handler.raise_if_blocked(
                verdict, event.event_type.value
            )
            event.apply_verdict_modifications(
                verdict, context
            )
