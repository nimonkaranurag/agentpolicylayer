from typing import Any

from apl.types import (
    ContextRequirement,
    EventType,
    PolicyDefinition,
    PolicyManifest,
)


class ManifestSerializer:
    def serialize(
        self, manifest: PolicyManifest
    ) -> dict[str, Any]:
        return {
            "server_name": manifest.server_name,
            "server_version": manifest.server_version,
            "protocol_version": manifest.protocol_version,
            "description": manifest.description,
            "supports_batch": manifest.supports_batch,
            "supports_streaming": manifest.supports_streaming,
            "documentation_url": manifest.documentation_url,
            "policies": [
                self._serialize_policy_definition(p)
                for p in manifest.policies
            ],
        }

    def deserialize(
        self, data: dict[str, Any]
    ) -> PolicyManifest:
        return PolicyManifest(
            server_name=data["server_name"],
            server_version=data["server_version"],
            protocol_version=data.get(
                "protocol_version", "0.3.0"
            ),
            description=data.get("description"),
            supports_batch=data.get(
                "supports_batch", False
            ),
            supports_streaming=data.get(
                "supports_streaming", False
            ),
            documentation_url=data.get(
                "documentation_url"
            ),
            policies=[
                self._deserialize_policy_definition(p)
                for p in data.get("policies", [])
            ],
        )

    def _serialize_policy_definition(
        self, policy: PolicyDefinition
    ) -> dict[str, Any]:
        return {
            "name": policy.name,
            "version": policy.version,
            "description": policy.description,
            "events": [e.value for e in policy.events],
            "context_requirements": [
                {
                    "path": c.path,
                    "required": c.required,
                    "description": c.description,
                }
                for c in policy.context_requirements
            ],
            "blocking": policy.blocking,
            "timeout_ms": policy.timeout_ms,
            "author": policy.author,
            "tags": policy.tags,
        }

    def _deserialize_policy_definition(
        self, data: dict[str, Any]
    ) -> PolicyDefinition:
        context_reqs = [
            ContextRequirement(
                path=c["path"],
                required=c.get("required", True),
                description=c.get("description"),
            )
            for c in data.get(
                "context_requirements", []
            )
        ]

        return PolicyDefinition(
            name=data["name"],
            version=data["version"],
            description=data.get("description"),
            events=[
                EventType(e)
                for e in data.get("events", [])
            ],
            context_requirements=context_reqs,
            blocking=data.get("blocking", True),
            timeout_ms=data.get("timeout_ms", 1000),
            author=data.get("author"),
            tags=data.get("tags", []),
        )
