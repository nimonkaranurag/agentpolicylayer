from __future__ import annotations

from pathlib import Path

from apl.server import PolicyServer

from .condition_evaluator import ConditionEvaluator
from .object_traversal import (
    get_nested_value_by_dot_path,
)
from .rule_evaluator import RuleEvaluator
from .schema import (
    YAMLManifest,
    YAMLPolicyDefinition,
    YAMLRule,
)
from .template_renderer import TemplateRenderer
from .yaml_policy_loader import YamlPolicyLoader
from .yaml_policy_validator import YamlPolicyValidator

_DEFAULT_LOADER: YamlPolicyLoader = YamlPolicyLoader()
_DEFAULT_VALIDATOR: YamlPolicyValidator = (
    YamlPolicyValidator()
)


def load_yaml_policy(path: Path | str) -> PolicyServer:
    return _DEFAULT_LOADER.load_from_file(path)


def validate_yaml_policy(
    path: Path | str,
) -> list[str]:
    return _DEFAULT_VALIDATOR.validate_file(path)


__all__: list[str] = [
    "load_yaml_policy",
    "validate_yaml_policy",
    "YamlPolicyLoader",
    "YamlPolicyValidator",
    "ConditionEvaluator",
    "RuleEvaluator",
    "TemplateRenderer",
    "YAMLManifest",
    "YAMLPolicyDefinition",
    "YAMLRule",
    "get_nested_value_by_dot_path",
]
