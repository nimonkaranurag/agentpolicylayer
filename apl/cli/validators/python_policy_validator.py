from __future__ import annotations

import ast
from pathlib import Path

from ..loaders.python_module_loader import (
    PythonModulePolicyLoader,
)
from .base_policy_validator import BasePolicyValidator


class PythonPolicyValidator(BasePolicyValidator):
    def __init__(self):
        self._loader = PythonModulePolicyLoader()

    def can_validate(self, path: Path) -> bool:
        return path.is_file() and path.suffix == ".py"

    def validate(self, path: Path) -> list[str]:
        syntax_errors = self._check_syntax(path)
        if syntax_errors:
            return syntax_errors
        return self._check_loaded_server(path)

    def _check_syntax(self, path: Path) -> list[str]:
        try:
            with open(path) as f:
                ast.parse(f.read())
            return []
        except SyntaxError as e:
            return [f"Syntax error: {e}"]

    def _check_loaded_server(self, path: Path) -> list[str]:
        from ...logging import get_logger

        logger = get_logger("validator")
        server = self._loader.load(path, logger)

        if server is None:
            return ["No PolicyServer instance found"]
        if not server.registry.all_policies():
            return [
                "PolicyServer has no" " registered policies"
            ]
        return []
