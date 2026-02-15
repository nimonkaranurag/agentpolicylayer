from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apl.server import PolicyServer


class BaseTransport(ABC):
    def __init__(self, server: "PolicyServer"):
        self._server = server

    @property
    def server(self) -> "PolicyServer":
        return self._server

    @abstractmethod
    def run(self) -> None: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
