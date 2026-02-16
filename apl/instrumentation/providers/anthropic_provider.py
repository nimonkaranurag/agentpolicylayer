from __future__ import annotations

from typing import Any

from .base_provider import BaseProvider


class AnthropicProvider(BaseProvider):

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @staticmethod
    def is_available() -> bool:
        try:
            import anthropic

            return True
        except ImportError:
            return False

    def patch_all_methods(self) -> None:
        from anthropic.resources import (
            AsyncMessages,
            Messages,
        )

        self.method_patcher.register_patch(
            Messages,
            "create",
            self._create_instance_method_sync_wrapper(
                patch_target_index=0
            ),
        )
        self.method_patcher.register_patch(
            AsyncMessages,
            "create",
            self._create_instance_method_async_wrapper(
                patch_target_index=1
            ),
        )
        self.method_patcher.apply_all_patches()

    def extract_text_from_response(
        self, response: Any
    ) -> str:
        try:
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
        except (AttributeError, IndexError):
            pass
        return ""

    def apply_text_to_response(self, response, new_text):
        try:
            response.content[0].text = new_text
        except (AttributeError, IndexError):
            pass
        return response
