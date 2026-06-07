from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from apl.composition import VerdictComposer
from apl.logging import APLLogger, get_logger
from apl.types import (
    CompositionConfig,
    Decision,
    EventPayload,
    EventType,
    FailMode,
    Message,
    SessionMetadata,
    Verdict,
)

from .decorator_evaluator import PolicyDecoratorFactory
from .event_builder import PolicyEventBuilder
from .policy_client import PolicyClient

logger: APLLogger = get_logger("layer")


class PolicyLayer:
    def __init__(
        self,
        composition: CompositionConfig | None = None,
    ) -> None:
        self._composition: CompositionConfig = composition or CompositionConfig()
        self._clients: list[PolicyClient] = []
        self._is_connected: bool = False
        self._composer: VerdictComposer = VerdictComposer(self._composition)
        self._event_builder: PolicyEventBuilder = PolicyEventBuilder()
        self._decorator_factory: PolicyDecoratorFactory = PolicyDecoratorFactory(self)

    @property
    def fail_mode(self) -> FailMode:
        """
        Configured behaviour when a policy cannot be evaluated.

        Public read accessor for ``composition.fail_mode`` so collaborators (e.g. the
        instrumentation evaluator) can honour fail-closed/open without reaching into the
        private composition config.
        """
        return self._composition.fail_mode

    def add_server(self, uri: str) -> PolicyLayer:
        client: PolicyClient = PolicyClient(uri, fail_mode=self._composition.fail_mode)
        self._clients.append(client)
        return self

    async def connect(self) -> None:
        if self._is_connected:
            return

        await asyncio.gather(*[client.connect() for client in self._clients])
        self._is_connected = True

        total_policies: int = sum(
            (len(client.manifest.policies) if client.manifest else 0)
            for client in self._clients
        )
        logger.info(
            f"PolicyLayer connected: {len(self._clients)} servers, "
            f"{total_policies} policies"
        )

    async def close(self) -> None:
        await asyncio.gather(*[client.close() for client in self._clients])
        self._is_connected = False

    async def evaluate(
        self,
        event_type: EventType | str,
        messages: list[Message] | None = None,
        payload: EventPayload | None = None,
        metadata: SessionMetadata | None = None,
    ) -> Verdict:
        if not self._is_connected:
            await self.connect()

        event = self._event_builder.build_from_evaluation_args(
            event_type=event_type,
            messages=messages,
            payload=payload,
            metadata=metadata,
        )

        start_time: float = time.perf_counter()
        try:
            verdicts: list[Verdict] = await self._collect_within_timeout(event)
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"Policy evaluation exceeded the "
                f"{self._composition.timeout_ms}ms layer timeout after "
                f"{elapsed_ms:.1f}ms; applying on_timeout="
                f"{self._composition.on_timeout.value}"
            )
            return self._timeout_verdict()
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        logger.debug(f"Evaluated {len(verdicts)} policies in {elapsed_ms:.1f}ms")

        return self._composer.compose(verdicts)

    def on(
        self,
        event_type: str,
        messages_from: Callable[[], list] | None = None,
    ) -> Callable:
        return self._decorator_factory.create_event_decorator(
            event_type=event_type,
            messages_from=messages_from,
        )

    def wrap(self, agent: Any) -> Any:
        """
        Wrap a supported agent/graph so APL policies fire during its execution.

        Currently supports LangGraph ``StateGraph`` objects, detected structurally (they
        expose ``add_node``/``add_edge``). An unsupported object raises ``TypeError``
        rather than being returned unmodified: silently handing back an unwrapped agent
        would run it with *no* enforcement — the exact fail-open trap this layer exists
        to prevent.
        """
        if hasattr(agent, "add_node") and hasattr(agent, "add_edge"):
            return self._wrap_langgraph(agent)

        raise TypeError(
            f"PolicyLayer.wrap() cannot wrap {type(agent).__name__!r}; expected a "
            "LangGraph StateGraph (an object exposing add_node/add_edge)."
        )

    def _wrap_langgraph(self, graph: Any) -> Any:
        # Imported lazily: keeps the LangGraph adapter (and its optional
        # dependency) off the common import path, and avoids a layer<->adapters
        # import cycle (the adapter imports PolicyLayer).
        from apl.adapters import APLGraphWrapper

        return APLGraphWrapper(self).wrap(graph)

    async def _collect_within_timeout(self, event: Any) -> list[Verdict]:
        timeout_ms: int = self._composition.timeout_ms
        if timeout_ms and timeout_ms > 0:
            return await asyncio.wait_for(
                self._collect_verdicts(event),
                timeout=timeout_ms / 1000,
            )
        # A non-positive timeout disables the budget rather than firing instantly.
        return await self._collect_verdicts(event)

    def _timeout_verdict(self) -> Verdict:
        """
        Build the single verdict to return when the layer timeout fires.

        ``on_timeout`` defaults to ``DENY`` so the layer is fail-closed: a slow or hung
        policy server blocks the action rather than silently allowing it. Only an
        explicit ``on_timeout=ALLOW`` downgrades a timeout to allow.
        """
        reasoning = (
            f"Policy evaluation exceeded the "
            f"{self._composition.timeout_ms}ms layer timeout"
        )
        if self._composition.on_timeout is Decision.ALLOW:
            return Verdict.allow(reasoning=reasoning)
        return Verdict.deny(reasoning=reasoning)

    async def _collect_verdicts(self, event: Any) -> list[Verdict]:
        if self._composition.parallel:
            return await self._collect_verdicts_parallel(event)
        return await self._collect_verdicts_sequential(event)

    async def _collect_verdicts_parallel(self, event: Any) -> list[Verdict]:
        nested_verdict_lists: list[list[Verdict]] = await asyncio.gather(
            *[client.evaluate(event) for client in self._clients]
        )
        return [
            verdict for verdict_list in nested_verdict_lists for verdict in verdict_list
        ]

    async def _collect_verdicts_sequential(self, event: Any) -> list[Verdict]:
        all_verdicts: list[Verdict] = []
        for client in self._clients:
            client_verdicts: list[Verdict] = await client.evaluate(event)
            all_verdicts.extend(client_verdicts)
        return all_verdicts
