from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ...server import PolicyServer


class BasePolicyLoader(ABC):
    @abstractmethod
    def can_load(self, path: Path) -> bool:
        ...

    @abstractmethod
    def load(
        self, path: Path, logger
    ) -> Optional[PolicyServer]:
        ...
