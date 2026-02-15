from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from apl.types import Message


class BaseMessageAdapter(ABC):

    @abstractmethod
    def to_apl_messages(
        self, raw_messages: Any
    ) -> list[Message]: ...

    def from_apl_messages(
        self, apl_messages: list[Message]
    ) -> list[dict[str, str | None]]:
        return [
            {"role": msg.role, "content": msg.content}
            for msg in apl_messages
        ]
