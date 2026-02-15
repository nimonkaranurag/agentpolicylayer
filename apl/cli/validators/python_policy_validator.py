from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

from ...server import PolicyServer
from .base_policy_validator import BasePolicyValidator


class PythonPolicyValidator(BasePolicyValidator):
    def can_validate(self, path: Path) -> bool:
        return path.is_file() and path.suffix == ".py"

    def validate(self, path: Path) -> list[str]:
        syntax_errors = self._check_syntax(path)
        if syntax_errors:
            return syntax_errors
        return self._check_policy_server_exists(path)

    def _check_syntax(self, path: Path) -> list[str]:
        try:
            with open(path) as f:
                ast.parse(f.read())
            return []
        except SyntaxError as e:
            return [f"Syntax error: {e}"]

    def _check_policy_server_exists(
        self, path: Path
    ) -> list[str]:
        errors = []
        try:
            spec = importlib.util.spec_from_file_location(
                "policy_module", path
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["policy_module"] = module
            spec.loader.exec_module(module)

            found_server = False
            for name in dir(module):
                obj = getattr(module, name)
                if isinstance(obj, PolicyServer):
                    found_server = True
                    if not obj.registry.all_policies():
                        errors.append(
                            "PolicyServer has no"
                            " registered policies"
                        )

            if not found_server:
                errors.append(
                    "No PolicyServer instance found"
                )

        except Exception as e:
            errors.append(f"Load error: {e}")

        return errors
