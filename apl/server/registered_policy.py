from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Union

from apl.types import (
    ContextRequirement,
    EventType,
    PolicyEvent,
    Verdict,
)

PolicyHandler = Callable[
    [PolicyEvent], Union[Verdict, Awaitable[Verdict]]
]


@dataclass
class RegisteredPolicy:
    name: str
    version: str
    handler: PolicyHandler
    events: list[EventType]
    context_requirements: list[ContextRequirement]
    blocking: bool
    timeout_ms: int
    description: str | None = None
