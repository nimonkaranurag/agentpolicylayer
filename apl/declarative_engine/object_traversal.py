from __future__ import annotations

from typing import Any


def get_nested_value_by_dot_path(
    obj: Any, dot_separated_path: str
) -> Any:
    if not dot_separated_path:
        return None
    
    parts: list[str] = dot_separated_path.split(".")
    current: Any = obj

    for part in parts:
        if current is None:
            return None

        if hasattr(current, part):
            current = getattr(current, part)
        elif (
            isinstance(current, dict)
            and part in current
        ):
            current = current[part]
        else:
            return None

    return current
