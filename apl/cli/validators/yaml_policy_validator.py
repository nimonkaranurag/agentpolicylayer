from __future__ import annotations

from pathlib import Path

from .base_policy_validator import BasePolicyValidator


class YamlPolicyValidator(BasePolicyValidator):
    SUPPORTED_EXTENSIONS = (".yaml", ".yml")

    def can_validate(self, path: Path) -> bool:
        return (
            path.is_file()
            and path.suffix
            in self.SUPPORTED_EXTENSIONS
        )

    def validate(self, path: Path) -> list[str]:
        from ...declarative_engine import (
            validate_yaml_policy,
        )

        return validate_yaml_policy(path)
