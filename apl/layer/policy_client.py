from __future__ import annotations

import logging
from typing import Any

from apl.serialization import (
    EventSerializer,
    ManifestSerializer,
    VerdictSerializer,
)
from apl.types import PolicyEvent, PolicyManifest, Verdict

from .client_transports import (
    BaseClientTransport,
    resolve_client_transport_for_uri,
)

logger: logging.Logger = logging.getLogger("apl")


class PolicyClient:

    def __init__(self, uri: str) -> None:
        self.uri: str = uri
        self.manifest: PolicyManifest | None = None
        self._transport: BaseClientTransport = (
            resolve_client_transport_for_uri(uri)
        )
        self._event_serializer: EventSerializer = (
            EventSerializer()
        )
        self._manifest_serializer: ManifestSerializer = (
            ManifestSerializer()
        )
        self._verdict_serializer: VerdictSerializer = (
            VerdictSerializer()
        )
        self._is_connected: bool = False

    async def connect(self) -> None:
        raw_manifest: dict[str, Any] | None = (
            await self._transport.connect()
        )

        if raw_manifest is not None:
            self.manifest = (
                self._manifest_serializer.deserialize(
                    raw_manifest
                )
            )
            policy_count: int = len(self.manifest.policies)
            logger.info(
                f"Connected to '{self.manifest.server_name}' "
                f"with {policy_count} policies via {self.uri}"
            )

        self._is_connected = True

    async def evaluate(
        self, event: PolicyEvent
    ) -> list[Verdict]:
        if not self._is_connected:
            await self.connect()

        serialized_event: dict[str, Any] = (
            self._event_serializer.serialize(event)
        )
        raw_verdicts: list[dict[str, Any]] = (
            await self._transport.evaluate(serialized_event)
        )

        if not raw_verdicts:
            return [
                Verdict.allow(
                    reasoning="No response from policy server"
                )
            ]

        return [
            self._verdict_serializer.deserialize(
                raw_verdict
            )
            for raw_verdict in raw_verdicts
        ]

    async def close(self) -> None:
        await self._transport.close()
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected
