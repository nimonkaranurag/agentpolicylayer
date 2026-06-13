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
    # What this policy returns when no rule matched. ``None`` means abstain
    # (OBSERVE) — neutral under composition. Set to ``"deny"`` to opt a policy into
    # deny-on-no-match (a default-deny allowlist), or ``"allow"``/``"observe"``.
    default_decision: str | None = None


@dataclass
class YAMLManifest:
    name: str
    version: str
    policies: list[YAMLPolicyDefinition]
    description: str | None = None
