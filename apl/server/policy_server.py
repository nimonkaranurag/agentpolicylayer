from apl.types import PolicyEvent, PolicyManifest, Verdict

from .manifest_generator import generate_manifest_from_server
from .policy_decorator import create_policy_decorator
from .policy_registry import PolicyRegistry


class PolicyServer:
    def __init__(
        self,
        name: str,
        version: str = "0.1.0",
        description: str | None = None,
    ):
        self.name = name
        self.version = version
        self.description = description
        self._registry = PolicyRegistry()

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
    ):
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

    async def evaluate(self, event: PolicyEvent) -> list[Verdict]:
        return await self._registry.evaluate_event(event)

    def get_manifest(self) -> PolicyManifest:
        return generate_manifest_from_server(self)

    def run(self, transport: str = "stdio", **kwargs) -> None:
        from apl.transports import create_transport

        transport_instance = create_transport(transport, self, **kwargs)
        transport_instance.run()
