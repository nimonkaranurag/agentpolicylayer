from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apl.types import (
        PolicyEvent,
        PolicyManifest,
        Verdict,
    )


class BaseClientTransport(abc.ABC):

    @abc.abstractmethod
    async def connect(
        self,
    ) -> PolicyManifest | None: ...

    @abc.abstractmethod
    async def evaluate(
        self, serialized_event: dict
    ) -> list[dict]: ...

    @abc.abstractmethod
    async def close(self) -> None: ...
