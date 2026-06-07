from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Iterator, List

from ..evaluation import PolicyEvaluator, VerdictHandler
from ..lifecycle.context import LifecycleContext
from ..lifecycle.sequence import EventSequence

if TYPE_CHECKING:
    from ..events.base_event import BaseEvent
    from ..state import InstrumentationState

ChunkTextExtractor = Callable[[Any], str]
ChunkTextApplier = Callable[[Any, str], None]


async def _aiter(items: List[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


class LifecycleExecutor:
    """
    Evaluate each event in a sequence and enforce its verdict.
    """

    def __init__(self, state: InstrumentationState) -> None:
        self.state: InstrumentationState = state
        self.policy_evaluator: PolicyEvaluator = PolicyEvaluator(state)
        self.verdict_handler: VerdictHandler = VerdictHandler()

    def _enforce_event(
        self,
        event: BaseEvent,
        verdict: Any,
        context: LifecycleContext,
    ) -> None:
        """
        The one place a verdict is enforced: block (raise) on deny/escalate, otherwise
        apply any modifications back onto the context.
        """
        self.verdict_handler.raise_if_blocked(verdict, event.event_type.value)
        event.apply_verdict_modifications(verdict, context)

    def execute_sequence(
        self,
        sequence: EventSequence,
        context: LifecycleContext,
    ) -> None:
        for event in sequence:
            verdict = self.policy_evaluator.evaluate_event_sync(event, context)
            self._enforce_event(event, verdict, context)

    async def execute_sequence_async(
        self,
        sequence: EventSequence,
        context: LifecycleContext,
    ) -> None:
        for event in sequence:
            verdict = await self.policy_evaluator.evaluate_event_async(event, context)
            self._enforce_event(event, verdict, context)

    # -- Streaming -----------------------------------------------------------------
    #
    # A streamed response is buffered *fully* and the output sequence runs *before* any
    # chunk is handed back to the caller. That is deliberate: for a guardrails product a
    # deny has to be able to stop the response, which is impossible once chunks have been
    # yielded. The cost is that instrumented streaming is no longer incremental — the
    # honest price of enforcing output policies on a stream (ENGINEERING_REVIEW §3.7).

    def enforce_sync_stream(
        self,
        stream: Iterator[Any],
        post_sequence: EventSequence,
        context: LifecycleContext,
        extract_chunk_text: ChunkTextExtractor,
        apply_chunk_text: ChunkTextApplier,
    ) -> Iterator[Any]:
        chunks, original_text = self._drain_sync(stream, extract_chunk_text)
        context.response_text = original_text
        self.execute_sequence(post_sequence, context)
        self._reconcile_text(
            chunks, original_text, context.response_text, apply_chunk_text
        )
        return iter(chunks)

    async def enforce_async_stream(
        self,
        stream: AsyncIterator[Any],
        post_sequence: EventSequence,
        context: LifecycleContext,
        extract_chunk_text: ChunkTextExtractor,
        apply_chunk_text: ChunkTextApplier,
    ) -> AsyncIterator[Any]:
        chunks: List[Any] = []
        parts: List[str] = []
        async for chunk in stream:
            chunks.append(chunk)
            parts.append(extract_chunk_text(chunk))
        original_text = "".join(parts)
        context.response_text = original_text
        await self.execute_sequence_async(post_sequence, context)
        self._reconcile_text(
            chunks, original_text, context.response_text, apply_chunk_text
        )
        return _aiter(chunks)

    @staticmethod
    def _drain_sync(
        stream: Iterator[Any],
        extract_chunk_text: ChunkTextExtractor,
    ) -> tuple[List[Any], str]:
        chunks: List[Any] = []
        parts: List[str] = []
        for chunk in stream:
            chunks.append(chunk)
            parts.append(extract_chunk_text(chunk))
        return chunks, "".join(parts)

    @staticmethod
    def _reconcile_text(
        chunks: List[Any],
        original_text: str,
        final_text: str,
        apply_chunk_text: ChunkTextApplier,
    ) -> None:
        """
        Reflect an output MODIFY back onto the buffered chunks.

        Original chunk boundaries can't be reconstructed once text changes, so the full
        modified text is carried by the first chunk and the rest are blanked — a
        consumer concatenating the deltas reads exactly the modified text.
        """
        if final_text == original_text:
            return
        for index, chunk in enumerate(chunks):
            apply_chunk_text(chunk, final_text if index == 0 else "")
