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
            self._create_sync_wrapper("sync_create"),
        )
        self.method_patcher.register_patch(
            AsyncMessages,
            "create",
            self._create_async_wrapper("async_create"),
        )
        self.method_patcher.apply_all_patches()

    def extract_messages_from_request(
        self, *args, **kwargs
    ) -> Any:
        return kwargs.get("messages", [])

    def extract_model_from_request(
        self, *args, **kwargs
    ) -> str:
        return kwargs.get("model", "unknown")

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

    def apply_text_to_response(
        self, response: Any, new_text: str
    ) -> Any:
        response.content[0].text = new_text
        return response

    def _create_sync_wrapper(self, patch_name: str):
        provider = self

        def wrapper(client_self, *args, **kwargs):
            original = (
                provider.method_patcher.patch_targets[
                    0
                ].original_method
            )
            bound_method = lambda *a, **kw: original(
                client_self, *a, **kw
            )
            return provider.execute_llm_call_sync(
                bound_method, *args, **kwargs
            )

        return wrapper

    def _create_async_wrapper(self, patch_name: str):
        provider = self

        async def wrapper(client_self, *args, **kwargs):
            original = (
                provider.method_patcher.patch_targets[
                    1
                ].original_method
            )

            async def bound_method(*a, **kw):
                return await original(client_self, *a, **kw)

            return await provider.execute_llm_call_async(
                bound_method, *args, **kwargs
            )

        return wrapper
