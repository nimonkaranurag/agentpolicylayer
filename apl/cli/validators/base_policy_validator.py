from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BasePolicyValidator(ABC):
    @abstractmethod
    def can_validate(self, path: Path) -> bool: ...

    @abstractmethod
    def validate(self, path: Path) -> list[str]: ...
