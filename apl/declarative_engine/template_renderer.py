from __future__ import annotations

import re
from typing import Any

from apl.types import PolicyEvent

from .object_traversal import (
    get_nested_value_by_dot_path,
)


class TemplateRenderer:

    TEMPLATE_VARIABLE_PATTERN: re.Pattern[str] = (
        re.compile(r"\{\{(.+?)\}\}")
    )

    def render(
        self, template: str, event: PolicyEvent
    ) -> str:
        if "{{" not in template:
            return template

        def replace_variable_reference(
            match: re.Match[str],
        ) -> str:
            dot_path: str = match.group(1).strip()
            resolved_value: Any = (
                get_nested_value_by_dot_path(
                    event, dot_path
                )
            )
            return (
                str(resolved_value)
                if resolved_value is not None
                else ""
            )

        return self.TEMPLATE_VARIABLE_PATTERN.sub(
            replace_variable_reference, template
        )
