from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def get_nested_value_by_dot_path(obj: Any, dot_separated_path: str) -> Any:
    """
    Resolve a dotted path (e.g. ``metadata.custom.region``) against an object.

    Mapping keys are resolved **before** attribute access, so a dict key whose name
    collides with a ``dict`` method (``items``, ``keys``, ``get``, ``values``, ...)
    returns the stored value rather than the bound method. Resolving attributes first
    (the previous behaviour) silently leaked methods and broke any rule referencing such
    a key. Returns ``None`` if any path segment is missing.
    """
    if not dot_separated_path:
        return None

    current: Any = obj
    for part in dot_separated_path.split("."):
        if current is None:
            return None

        if isinstance(current, Mapping):
            if part not in current:
                return None
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None

    return current
