from abc import ABC, abstractmethod
from typing import Any, List

from apl.types import Message


class BaseMessageAdapter(ABC):
    @abstractmethod
    def to_apl_messages(
        self, raw_messages: Any
    ) -> List[Message]: ...

    @abstractmethod
    def from_apl_messages(
        self, apl_messages: List[Message]
    ) -> Any: ...
