from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from apl.composition import VerdictComposer
from apl.types import (
    CompositionConfig,
    EventPayload,
    EventType,
    Message,
    SessionMetadata,
    Verdict,
)

from .decorator_evaluator import PolicyDecoratorFactory
from .event_builder import PolicyEventBuilder
from .policy_client import PolicyClient

logger: logging.Logger = logging.getLogger("apl")


class PolicyLayer:

    def __init__(
        self,
        composition: CompositionConfig | None = None,
    ) -> None:
        self._composition: CompositionConfig = (
            composition or CompositionConfig()
        )
        self._clients: list[PolicyClient] = []
        self._is_connected: bool = False
        self._composer: VerdictComposer = (
            VerdictComposer(self._composition)
        )
        self._event_builder: PolicyEventBuilder = (
            PolicyEventBuilder()
        )
        self._decorator_factory: (
            PolicyDecoratorFactory
        ) = PolicyDecoratorFactory(self)

    def add_server(self, uri: str) -> PolicyLayer:
        client: PolicyClient = PolicyClient(uri)
        self._clients.append(client)
        return self

    async def connect(self) -> None:
        if self._is_connected:
            return

        await asyncio.gather(
            *[
                client.connect()
                for client in self._clients
            ]
        )
        self._is_connected = True

        total_policies: int = sum(
            (
                len(client.manifest.policies)
                if client.manifest
                else 0
            )
            for client in self._clients
        )
        logger.info(
            f"PolicyLayer connected: {len(self._clients)} servers, "
            f"{total_policies} policies"
        )

    async def close(self) -> None:
        await asyncio.gather(
            *[
                client.close()
                for client in self._clients
            ]
        )
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
        verdicts: list[Verdict] = (
            await self._collect_verdicts(event)
        )
        elapsed_ms: float = (
            time.perf_counter() - start_time
        ) * 1000

        logger.debug(
            f"Evaluated {len(verdicts)} policies in {elapsed_ms:.1f}ms"
        )

        return self._composer.compose(verdicts)

    def on(
        self,
        event_type: str,
        messages_from: (
            Callable[[], list] | None
        ) = None,
    ) -> Callable:
        return self._decorator_factory.create_event_decorator(
            event_type=event_type,
            messages_from=messages_from,
        )

    def wrap(self, agent: Any) -> Any:
        agent_type_name: str = type(agent).__name__

        if hasattr(agent, "add_node") and hasattr(
            agent, "add_edge"
        ):
            return self._wrap_langgraph(agent)

        logger.warning(
            f"Unknown agent type: {agent_type_name}, returning unwrapped"
        )
        return agent

    def _wrap_langgraph(self, graph: Any) -> Any:
        logger.info(
            "LangGraph wrapper not yet implemented"
        )
        return graph

    async def _collect_verdicts(
        self, event: Any
    ) -> list[Verdict]:
        if self._composition.parallel:
            return (
                await self._collect_verdicts_parallel(
                    event
                )
            )
        return await self._collect_verdicts_sequential(
            event
        )

    async def _collect_verdicts_parallel(
        self, event: Any
    ) -> list[Verdict]:
        nested_verdict_lists: list[list[Verdict]] = (
            await asyncio.gather(
                *[
                    client.evaluate(event)
                    for client in self._clients
                ]
            )
        )
        return [
            verdict
            for verdict_list in nested_verdict_lists
            for verdict in verdict_list
        ]

    async def _collect_verdicts_sequential(
        self, event: Any
    ) -> list[Verdict]:
        all_verdicts: list[Verdict] = []
        for client in self._clients:
            client_verdicts: list[Verdict] = (
                await client.evaluate(event)
            )
            all_verdicts.extend(client_verdicts)
        return all_verdicts
