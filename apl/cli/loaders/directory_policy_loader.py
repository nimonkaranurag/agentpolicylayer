from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...server import PolicyServer
from .base_policy_loader import BasePolicyLoader
from .python_module_loader import (
    PythonModulePolicyLoader,
)


class DirectoryPolicyLoader(BasePolicyLoader):
    def __init__(self):
        self._python_loader = PythonModulePolicyLoader()

    def can_load(self, path: Path) -> bool:
        return path.is_dir()

    def load(
        self, path: Path, logger
    ) -> Optional[PolicyServer]:
        server = PolicyServer(
            name=path.name, version="1.0.0"
        )

        loaded_count = 0
        for file in path.iterdir():
            if not self._is_loadable_python(file):
                continue

            sub_server = self._python_loader.load(
                file, logger
            )
            if sub_server:
                self._merge_policies(server, sub_server)
                loaded_count += 1

        return server if loaded_count > 0 else None

    @staticmethod
    def _is_loadable_python(file: Path) -> bool:
        return (
            file.suffix == ".py"
            and not file.name.startswith("_")
        )

    @staticmethod
    def _merge_policies(target, source):
        for policy in source.registry.all_policies():
            target.registry.register(policy)
