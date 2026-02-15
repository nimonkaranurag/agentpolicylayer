from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base_policy_validator import BasePolicyValidator
from .python_policy_validator import (
    PythonPolicyValidator,
)
from .yaml_policy_validator import YamlPolicyValidator


class PolicyValidatorRegistry:
    def __init__(self):
        self._validators: list[BasePolicyValidator] = [
            PythonPolicyValidator(),
            YamlPolicyValidator(),
        ]

    def find_validator_for_path(
        self, path: Path
    ) -> Optional[BasePolicyValidator]:
        for validator in self._validators:
            if validator.can_validate(path):
                return validator
        return None

    def validate(self, path: Path) -> list[str]:
        validator = self.find_validator_for_path(path)
        if validator is None:
            return [
                f"Unsupported file type: {path.suffix}"
            ]
        return validator.validate(path)
