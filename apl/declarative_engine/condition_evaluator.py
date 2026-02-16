from __future__ import annotations

import re
from typing import Any, Callable

ConditionHandler = Callable[[Any, Any], bool]


class ConditionEvaluator:

    def __init__(self) -> None:
        self._handler_registry: dict[
            str, ConditionHandler
        ] = {
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

    def evaluate(
        self, value: Any, condition: Any
    ) -> bool:
        if condition is None:
            return value is None

        if isinstance(condition, dict):
            return self._evaluate_dict_condition(
                value, condition
            )

        return value == condition

    def _evaluate_dict_condition(
        self, value, condition
    ):
        results = []
        for (
            operator_name,
            operator_argument,
        ) in condition.items():
            handler = self._handler_registry.get(
                operator_name
            )
            if handler is not None:
                results.append(
                    handler(value, operator_argument)
                )
        if results:
            return all(results)
        return value == condition

    @staticmethod
    def _handle_equals(
        value: Any, expected: Any
    ) -> bool:
        return value == expected

    @staticmethod
    def _handle_regex_match(
        value: Any, pattern: str
    ) -> bool:
        if value is None:
            return False
        return bool(
            re.match(
                pattern, str(value), re.IGNORECASE
            )
        )

    @staticmethod
    def _handle_contains(
        value: Any, needle: Any
    ) -> bool:
        if value is None:
            return False
        if isinstance(
            value, (str, list, tuple, set, dict)
        ):
            return needle in value
        return False

    @staticmethod
    def _handle_greater_than(
        value: Any, threshold: Any
    ) -> bool:
        return value is not None and value > threshold

    @staticmethod
    def _handle_greater_than_or_equal(
        value: Any, threshold: Any
    ) -> bool:
        return value is not None and value >= threshold

    @staticmethod
    def _handle_less_than(
        value: Any, threshold: Any
    ) -> bool:
        return value is not None and value < threshold

    @staticmethod
    def _handle_less_than_or_equal(
        value: Any, threshold: Any
    ) -> bool:
        return value is not None and value <= threshold

    @staticmethod
    def _handle_membership(
        value: Any, allowed_values: list[Any]
    ) -> bool:
        return value in allowed_values

    def _handle_negation(
        self, value: Any, inner_condition: Any
    ) -> bool:
        return not self.evaluate(
            value, inner_condition
        )

    def _handle_any_of(
        self, value: Any, conditions: list[Any]
    ) -> bool:
        return any(
            self.evaluate(value, c) for c in conditions
        )

    def _handle_all_of(
        self, value: Any, conditions: list[Any]
    ) -> bool:
        return all(
            self.evaluate(value, c) for c in conditions
        )
