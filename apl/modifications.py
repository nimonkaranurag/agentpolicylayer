"""
The single place a :class:`~apl.types.Modification` is turned into a new value.

Historically three different call sites applied verdict modifications — the server's
sequential evaluator, the in-process instrumentation events, and the decorator — and
each one read only ``target``/``value`` and silently ignored ``operation`` and
``path``. So ``redact``/``append``/``prepend``/``patch`` all degraded to ``replace``
(ENGINEERING_REVIEW §3.4). This module is the one operation dispatcher all three now
route through, so an operation means the same thing everywhere.

Design notes:

- The dispatcher is a pure function of ``(current_value, modification)``. ``append``,
  ``prepend``, ``patch`` and path-scoped ``redact`` all need the current value, so the
  callers read it, hand it here, and write back the result.
- It fails **closed**: an operation that cannot be applied (unknown operation, ``patch``
  with no ``path``, a path that does not resolve, an incompatible type) raises rather
  than silently leaving the value unmodified. Letting an action proceed *without* the
  modification a policy demanded is exactly the fail-open behaviour this product must not
  have.
- ``patch``/``redact`` deep-copy the value before mutating it, so a policy that returns a
  shared/module-level object never has that object mutated across evaluations.
"""

from __future__ import annotations

import copy
from typing import Any, Union

from apl.types import Modification

#: Marker substituted by ``redact`` when the modification carries no explicit value.
DEFAULT_REDACTION = "[REDACTED]"

PathToken = Union[str, int]


def apply_operation(current: Any, modification: Modification) -> Any:
    """
    Apply ``modification`` to ``current`` and return the new value.

    ``current`` is the value the modification targets *right now* (the response text,
    the tool args, the prompt messages, ...). The result is what the target should
    become; the caller is responsible for writing it back.

    Raises:
        ValueError: unknown operation, or ``patch`` without a ``path``, or a malformed
            ``path``.
        KeyError / IndexError: a ``path`` that does not resolve against ``current``.
        TypeError: ``append``/``prepend`` on a value that cannot be combined with
            ``modification.value``.
    """
    operation = modification.operation

    if operation == "replace":
        return modification.value

    if operation == "append":
        return _combine(current, modification.value, prepend=False)

    if operation == "prepend":
        return _combine(current, modification.value, prepend=True)

    if operation == "redact":
        marker = (
            modification.value if modification.value is not None else DEFAULT_REDACTION
        )
        if modification.path:
            return _set_at_path(current, modification.path, marker)
        return marker

    if operation == "patch":
        if not modification.path:
            raise ValueError("Modification operation 'patch' requires a 'path'")
        return _set_at_path(current, modification.path, modification.value)

    raise ValueError(f"Unsupported modification operation: {operation!r}")


def _combine(current: Any, value: Any, *, prepend: bool) -> Any:
    """Concatenate ``value`` onto ``current`` (str/list/dict), order set by
    ``prepend``.
    """
    if current is None:
        return value

    if isinstance(current, str):
        addition = str(value)
        return addition + current if prepend else current + addition

    if isinstance(current, (list, tuple)):
        base = list(current)
        addition = list(value) if isinstance(value, (list, tuple)) else [value]
        combined = addition + base if prepend else base + addition
        return tuple(combined) if isinstance(current, tuple) else combined

    if isinstance(current, dict) and isinstance(value, dict):
        # On key conflicts the *later* mapping wins, matching dict-merge intuition:
        # append => value overrides; prepend => existing keys override.
        return {**value, **current} if prepend else {**current, **value}

    raise TypeError(
        f"Cannot {'prepend to' if prepend else 'append to'} a value of type "
        f"{type(current).__name__} with a value of type {type(value).__name__}"
    )


def _set_at_path(root: Any, path: str, value: Any) -> Any:
    """
    Return a deep copy of ``root`` with the leaf at ``path`` set to ``value``.

    Intermediate containers must already exist (fail closed: we do not silently build
    out a structure the policy did not mention). The final key may be created on a dict.
    """
    tokens = _parse_path(path)
    if not tokens:
        raise ValueError(f"Empty modification path: {path!r}")

    result = copy.deepcopy(root)
    cursor = result
    for token in tokens[:-1]:
        cursor = _descend(cursor, token, path)
    _assign(cursor, tokens[-1], value, path)
    return result


def _parse_path(path: str) -> list[PathToken]:
    """
    Parse a small JSON-path subset into tokens: dict keys and ``[int]`` list indices.

    Supported: ``$.a.b``, ``a.b``, ``$.items[0].name``. Anything richer (wildcards,
    filters, quoted keys) is rejected — keep the 90% path obvious and fail closed on
    the rest.
    """
    body = path[1:] if path.startswith("$") else path
    body = body.lstrip(".")
    if not body:
        return []

    tokens: list[PathToken] = []
    for segment in body.split("."):
        bracket_start = segment.find("[")
        key = segment if bracket_start == -1 else segment[:bracket_start]
        if key:
            tokens.append(key)

        remainder = "" if bracket_start == -1 else segment[bracket_start:]
        while remainder:
            if not remainder.startswith("["):
                raise ValueError(f"Malformed path segment {segment!r} in {path!r}")
            end = remainder.find("]")
            if end == -1:
                raise ValueError(f"Malformed path segment {segment!r} in {path!r}")
            index_text = remainder[1:end]
            try:
                tokens.append(int(index_text))
            except ValueError as exc:
                raise ValueError(
                    f"Non-integer list index {index_text!r} in path {path!r}"
                ) from exc
            remainder = remainder[end + 1 :]

    return tokens


def _descend(container: Any, token: PathToken, path: str) -> Any:
    if isinstance(token, int):
        if not isinstance(container, list):
            raise TypeError(
                f"Path {path!r}: expected a list to index by {token}, "
                f"got {type(container).__name__}"
            )
        try:
            return container[token]
        except IndexError as exc:
            raise IndexError(f"Path {path!r}: list index {token} out of range") from exc

    if not isinstance(container, dict):
        raise TypeError(
            f"Path {path!r}: expected a dict to look up {token!r}, "
            f"got {type(container).__name__}"
        )
    if token not in container:
        raise KeyError(f"Path {path!r}: key {token!r} not found")
    return container[token]


def _assign(container: Any, token: PathToken, value: Any, path: str) -> None:
    if isinstance(token, int):
        if not isinstance(container, list):
            raise TypeError(
                f"Path {path!r}: expected a list to index by {token}, "
                f"got {type(container).__name__}"
            )
        try:
            container[token] = value
        except IndexError as exc:
            raise IndexError(f"Path {path!r}: list index {token} out of range") from exc
        return

    if not isinstance(container, dict):
        raise TypeError(
            f"Path {path!r}: expected a dict to assign {token!r}, "
            f"got {type(container).__name__}"
        )
    container[token] = value
