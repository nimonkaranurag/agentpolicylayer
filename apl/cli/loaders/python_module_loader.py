from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

from ...server import PolicyServer
from .base_policy_loader import BasePolicyLoader


class PythonModulePolicyLoader(BasePolicyLoader):
    def can_load(self, path: Path) -> bool:
        return path.is_file() and path.suffix == ".py"

    def load(
        self, path: Path, logger
    ) -> Optional[PolicyServer]:
        try:
            module = self._import_module(path)
            return self._find_policy_server(
                module, path, logger
            )
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
            return None

    def _import_module(self, path: Path):
        spec = importlib.util.spec_from_file_location(
            "policy_module", path
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["policy_module"] = module
        spec.loader.exec_module(module)
        return module

    def _find_policy_server(
        self, module, path: Path, logger
    ) -> Optional[PolicyServer]:
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, PolicyServer):
                return obj

        logger.error(
            f"No PolicyServer found in {path}"
        )
        return None
