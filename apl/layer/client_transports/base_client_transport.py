from __future__ import annotations

import abc


class BaseClientTransport(abc.ABC):
    """
    Contract for a client-side connection to a policy server.

    ``connect`` returns the raw manifest payload (the client decodes/validates it);
    ``evaluate`` returns raw verdict payloads. Implementations must raise
    :class:`apl.types.PolicyUnavailableError` on any availability failure so the client
    can fail closed.
    """

    @abc.abstractmethod
    async def connect(self) -> dict | None: ...

    @abc.abstractmethod
    async def evaluate(self, serialized_event: dict) -> list[dict]: ...

    @abc.abstractmethod
    async def close(self) -> None: ...
