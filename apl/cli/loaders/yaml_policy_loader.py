from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...server import PolicyServer
from .base_policy_loader import BasePolicyLoader


class YamlPolicyLoader(BasePolicyLoader):
    SUPPORTED_EXTENSIONS = (".yaml", ".yml")

    def can_load(self, path: Path) -> bool:
        return (
            path.is_file()
            and path.suffix in self.SUPPORTED_EXTENSIONS
        )

    def load(
        self, path: Path, logger
    ) -> Optional[PolicyServer]:
        from ...declarative_engine import load_yaml_policy

        try:
            return load_yaml_policy(path)
        except Exception as e:
            logger.error(f"Failed to load YAML policy: {e}")
            return None
