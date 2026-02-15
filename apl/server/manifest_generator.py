from __future__ import annotations

from typing import TYPE_CHECKING

from apl.types import PolicyDefinition, PolicyManifest

if TYPE_CHECKING:
    from .policy_server import PolicyServer
    from .registered_policy import RegisteredPolicy


def generate_manifest_from_server(
    server: PolicyServer,
) -> PolicyManifest:
    registered_policies: list[RegisteredPolicy] = (
        server.registry.all_policies()
    )

    policy_definitions: list[PolicyDefinition] = [
        PolicyDefinition(
            name=policy.name,
            version=policy.version,
            description=policy.description,
            events=policy.events,
            context_requirements=policy.context_requirements,
            blocking=policy.blocking,
            timeout_ms=policy.timeout_ms,
        )
        for policy in registered_policies
    ]

    return PolicyManifest(
        server_name=server.name,
        server_version=server.version,
        description=server.description,
        policies=policy_definitions,
    )
