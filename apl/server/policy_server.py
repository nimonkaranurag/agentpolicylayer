from __future__ import annotations

from typing import Callable

from apl.types import (
    PolicyEvent,
    PolicyManifest,
    Verdict,
)

from .manifest_generator import (
    generate_manifest_from_server,
)
from .policy_decorator import create_policy_decorator
from .policy_registry import PolicyRegistry
from .registered_policy import PolicyHandler


class PolicyServer:

    def __init__(
        self,
        name: str,
        version: str = "0.3.0",
        description: str | None = None,
    ) -> None:
        self.name: str = name
        self.version: str = version
        self.description: str | None = description
        self._registry: PolicyRegistry = (
            PolicyRegistry()
        )

    @property
    def registry(self) -> PolicyRegistry:
        return self._registry

    def policy(
        self,
        name: str,
        events: list[str],
        context: list[str] | None = None,
        version: str = "1.0.0",
        blocking: bool = True,
        timeout_ms: int = 1000,
        description: str | None = None,
    ) -> Callable[[PolicyHandler], PolicyHandler]:
        return create_policy_decorator(
            registry=self._registry,
            policy_name=name,
            events=events,
            version=version,
            context=context,
            blocking=blocking,
            timeout_ms=timeout_ms,
            description=description,
        )

    async def evaluate(
        self, event: PolicyEvent
    ) -> list[Verdict]:
        return await self._registry.evaluate_event(
            event
        )

    def get_manifest(self) -> PolicyManifest:
        return generate_manifest_from_server(self)

    def run(
        self, transport: str = "stdio", **kwargs
    ) -> None:
        from apl.transports import create_transport

        transport_instance = create_transport(
            transport, self, **kwargs
        )
        transport_instance.run()
