from __future__ import annotations

from typing import Any, Optional

from pydantic import ValidationError

from apl.logging import APLLogger, get_logger
from apl.serialization import (
    manifest_from_wire,
    to_wire,
    verdict_from_wire,
)
from apl.types import (
    PROTOCOL_VERSION,
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

logger: APLLogger = get_logger("layer.client")


def _major(version: str) -> Optional[int]:
    try:
        return int(version.split(".", 1)[0])
    except (AttributeError, ValueError, IndexError):
        return None


def _assert_protocol_compatible(server_version: str, uri: str) -> None:
    """
    Reject a server whose protocol *major* version differs from ours.

    A differing major version means incompatible wire semantics, so we fail closed by
    raising :class:`PolicyUnavailableError` (the caller turns that into a deny). A
    differing minor/patch — or a version we can't parse — is warned about but allowed
    through.
    """
    if server_version == PROTOCOL_VERSION:
        return

    server_major = _major(server_version)
    ours_major = _major(PROTOCOL_VERSION)
    if server_major is None or ours_major is None:
        logger.warning(
            f"Policy server {uri} reports protocol '{server_version}'; this "
            f"client speaks '{PROTOCOL_VERSION}' and could not compare them."
        )
        return

    if server_major != ours_major:
        raise PolicyUnavailableError(
            f"incompatible policy protocol: server {uri} speaks "
            f"'{server_version}', this client requires major version "
            f"'{ours_major}' (speaks '{PROTOCOL_VERSION}')"
        )

    logger.warning(
        f"Policy server {uri} speaks protocol '{server_version}'; this client "
        f"speaks '{PROTOCOL_VERSION}'. Same major version — proceeding."
    )


class PolicyClient:
    def __init__(self, uri: str, fail_mode: FailMode = FailMode.CLOSED) -> None:
        self.uri: str = uri
        self._fail_mode: FailMode = fail_mode
        self.manifest: Optional[PolicyManifest] = None
        self._transport: BaseClientTransport = resolve_client_transport_for_uri(uri)
        self._is_connected: bool = False

    async def connect(self) -> None:
        raw_manifest: Optional[dict[str, Any]] = await self._transport.connect()

        if raw_manifest is not None:
            try:
                self.manifest = manifest_from_wire(raw_manifest)
            except ValidationError as exc:
                raise PolicyUnavailableError(
                    f"invalid manifest from {self.uri}: {exc}"
                ) from exc

            _assert_protocol_compatible(self.manifest.protocol_version, self.uri)

            policy_count: int = len(self.manifest.policies)
            logger.info(
                f"Connected to '{self.manifest.server_name}' "
                f"with {policy_count} policies via {self.uri}"
            )

        self._is_connected = True

    async def evaluate(self, event: PolicyEvent) -> list[Verdict]:
        serialized_event: dict[str, Any] = to_wire(event)

        try:
            if not self._is_connected:
                await self.connect()

            raw_verdicts: list[dict[str, Any]] = await self._transport.evaluate(
                serialized_event
            )
            # An empty list here means the server responded but no policy
            # produced a verdict (it has no opinion) — distinct from being
            # unavailable, which raises. How a globally-empty verdict set
            # composes is the composer's concern (WP-2), not the client's.
            return [verdict_from_wire(raw_verdict) for raw_verdict in raw_verdicts]
        except PolicyUnavailableError as exc:
            # Covers a failed connect (unreachable server, incompatible protocol,
            # or a malformed manifest), a transport error during evaluate, and a
            # malformed verdict payload — all of which must fail closed.
            logger.error(f"Policy server unavailable ({self.uri}): {exc}")
            return [
                Verdict.unavailable(
                    self._fail_mode,
                    reasoning=f"Policy server unavailable: {exc}",
                )
            ]

    async def close(self) -> None:
        await self._transport.close()
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected
