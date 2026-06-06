from __future__ import annotations

import logging
from typing import Any

from apl.serialization import (
    EventSerializer,
    ManifestSerializer,
    VerdictSerializer,
)
from apl.types import (
    FailMode,
    PolicyEvent,
    PolicyManifest,
    PolicyUnavailableError,
    Verdict,
)

from .client_transports import (
    BaseClientTransport,
    resolve_client_transport_for_uri,
)

logger: logging.Logger = logging.getLogger("apl")


class PolicyClient:
    def __init__(self, uri: str, fail_mode: FailMode = FailMode.CLOSED) -> None:
        self.uri: str = uri
        self._fail_mode: FailMode = fail_mode
        self.manifest: PolicyManifest | None = None
        self._transport: BaseClientTransport = resolve_client_transport_for_uri(uri)
        self._event_serializer: EventSerializer = EventSerializer()
        self._manifest_serializer: ManifestSerializer = ManifestSerializer()
        self._verdict_serializer: VerdictSerializer = VerdictSerializer()
        self._is_connected: bool = False

    async def connect(self) -> None:
        raw_manifest: dict[str, Any] | None = await self._transport.connect()

        if raw_manifest is not None:
            self.manifest = self._manifest_serializer.deserialize(raw_manifest)
            policy_count: int = len(self.manifest.policies)
            logger.info(
                f"Connected to '{self.manifest.server_name}' "
                f"with {policy_count} policies via {self.uri}"
            )

        self._is_connected = True

    async def evaluate(self, event: PolicyEvent) -> list[Verdict]:
        if not self._is_connected:
            await self.connect()

        serialized_event: dict[str, Any] = self._event_serializer.serialize(event)

        try:
            raw_verdicts: list[dict[str, Any]] = await self._transport.evaluate(
                serialized_event
            )
        except PolicyUnavailableError as exc:
            logger.error(f"Policy server unavailable ({self.uri}): {exc}")
            return [
                Verdict.unavailable(
                    self._fail_mode,
                    reasoning=f"Policy server unavailable: {exc}",
                )
            ]

        # An empty list here means the server responded but no policy produced a
        # verdict (it has no opinion) — that is distinct from being unavailable,
        # which raises above. How a globally-empty verdict set composes is the
        # composer's concern (WP-2's empty-input semantics), not the client's.
        return [
            self._verdict_serializer.deserialize(raw_verdict)
            for raw_verdict in raw_verdicts
        ]

    async def close(self) -> None:
        await self._transport.close()
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected
