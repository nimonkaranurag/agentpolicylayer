from __future__ import annotations

import re
from typing import Any, Callable

ConditionHandler = Callable[[Any, Any], bool]


class ConditionEvaluator:
    def __init__(self) -> None:
        self._handler_registry: dict[str, ConditionHandler] = {
            "equals": self._handle_equals,
            "matches": self._handle_regex_match,
            "contains": self._handle_contains,
            "gt": self._handle_greater_than,
            "gte": self._handle_greater_than_or_equal,
            "lt": self._handle_less_than,
            "lte": self._handle_less_than_or_equal,
            "in": self._handle_membership,
            "not": self._handle_negation,
            "any": self._handle_any_of,
            "all": self._handle_all_of,
        }

    def register_condition(
        self,
        operator_name: str,
        handler: ConditionHandler,
    ) -> None:
        self._handler_registry[operator_name] = handler

    @property
    def known_operators(self) -> frozenset[str]:
        """
        The operator names this evaluator recognises (built-ins + any registered via
        :meth:`register_condition`).

        The YAML validator reads this so ``apl validate`` and the evaluator agree on
        exactly one vocabulary.
        """
        return frozenset(self._handler_registry)

    def evaluate(self, value: Any, condition: Any) -> bool:
        if condition is None:
            return value is None

        if isinstance(condition, dict):
            return self._evaluate_dict_condition(value, condition)

        return value == condition

    def _evaluate_dict_condition(self, value: Any, condition: dict[str, Any]) -> bool:
        """
        Evaluate an operator mapping (``{"contains": "x", "gt": 1}`` -> all must hold).

        Every key must be a known operator. An unknown operator (typically a typo such
        as ``contians:``) or an empty mapping raises rather than silently disabling the
        rule — for a guardrails product a misconfigured condition must fail loudly, not
        under-enforce. Compare against a literal dict with the explicit ``equals``
        operator.
        """
        if not condition:
            raise ValueError(
                "Empty condition mapping; expected at least one operator from: "
                f"{self._sorted_operators()}"
            )

        results: list[bool] = []
        for operator_name, operator_argument in condition.items():
            handler = self._handler_registry.get(operator_name)
            if handler is None:
                raise ValueError(
                    f"Unknown condition operator {operator_name!r}; "
                    f"valid operators: {self._sorted_operators()}"
                )
            results.append(handler(value, operator_argument))
        return all(results)

    def _sorted_operators(self) -> str:
        return ", ".join(sorted(self._handler_registry))

    @staticmethod
    def _handle_equals(value: Any, expected: Any) -> bool:
        return value == expected

    @staticmethod
    def _handle_regex_match(value: Any, pattern: Any) -> bool:
        """
        ``matches`` semantics: case-insensitive :func:`re.search`, i.e. the pattern may
        match *anywhere* in the value (not only the start, as ``re.match`` would).

        ``re.search`` is the fail-closed choice for a detection rule — e.g. ``matches:
        SECRET`` fires on ``"this has SECRET"`` instead of silently passing it. An
        invalid or non-string pattern raises ``ValueError`` rather than silently never
        matching.
        """
        if value is None:
            return False
        try:
            return bool(re.search(pattern, str(value), re.IGNORECASE))
        except (re.error, TypeError) as exc:
            raise ValueError(
                f"Invalid 'matches' regex pattern {pattern!r}: {exc}"
            ) from exc

    @staticmethod
    def _handle_contains(value: Any, needle: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, (str, list, tuple, set, dict)):
            return needle in value
        return False

    @staticmethod
    def _handle_greater_than(value: Any, threshold: Any) -> bool:
        return value is not None and value > threshold

    @staticmethod
    def _handle_greater_than_or_equal(value: Any, threshold: Any) -> bool:
        return value is not None and value >= threshold

    @staticmethod
    def _handle_less_than(value: Any, threshold: Any) -> bool:
        return value is not None and value < threshold

    @staticmethod
    def _handle_less_than_or_equal(value: Any, threshold: Any) -> bool:
        return value is not None and value <= threshold

    @staticmethod
    def _handle_membership(value: Any, allowed_values: Any) -> bool:
        # `in` is membership against a *collection*. A bare string argument
        # (``in: "admin,user"``) would silently become substring matching, so
        # "min,us" reads as allowlisted — a fail-open in the natural
        # `not: {in: [...]}` allowlist pattern. Require a real list/tuple/set and
        # fail closed otherwise.
        if not isinstance(allowed_values, (list, tuple, set)):
            raise ValueError(
                "'in' expects a list of allowed values, got "
                f"{type(allowed_values).__name__}; a string argument would match "
                "substrings (allowlist bypass)"
            )
        return value in allowed_values

    def _handle_negation(self, value: Any, inner_condition: Any) -> bool:
        return not self.evaluate(value, inner_condition)

    def _handle_any_of(self, value: Any, conditions: list[Any]) -> bool:
        return any(self.evaluate(value, c) for c in conditions)

    def _handle_all_of(self, value: Any, conditions: list[Any]) -> bool:
        return all(self.evaluate(value, c) for c in conditions)
