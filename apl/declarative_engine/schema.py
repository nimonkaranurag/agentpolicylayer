from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class YAMLRule:
    when: dict[str, Any]
    then: dict[str, Any]


@dataclass
class YAMLPolicyDefinition:
    name: str
    events: list[str]
    rules: list[YAMLRule]
    description: str | None = None
    version: str = "1.0.0"
    blocking: bool = True
    timeout_ms: int = 1000


@dataclass
class YAMLManifest:
    name: str
    version: str
    policies: list[YAMLPolicyDefinition]
    description: str | None = None
