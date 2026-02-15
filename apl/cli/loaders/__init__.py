from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...server import PolicyServer
from .base_policy_loader import BasePolicyLoader
from .directory_policy_loader import (
    DirectoryPolicyLoader,
)
from .python_module_loader import (
    PythonModulePolicyLoader,
)
from .yaml_policy_loader import YamlPolicyLoader


class PolicyLoaderRegistry:
    def __init__(self):
        self._loaders: list[BasePolicyLoader] = [
            DirectoryPolicyLoader(),
            PythonModulePolicyLoader(),
            YamlPolicyLoader(),
        ]

    def find_loader_for_path(
        self, path: Path
    ) -> Optional[BasePolicyLoader]:
        for loader in self._loaders:
            if loader.can_load(path):
                return loader
        return None

    def load(
        self, path: Path, logger
    ) -> Optional[PolicyServer]:
        loader = self.find_loader_for_path(path)
        if loader is None:
            return None
        return loader.load(path, logger)
