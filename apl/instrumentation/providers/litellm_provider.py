import functools
from typing import Any

from .base_provider import BaseProvider


class LiteLLMProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "litellm"

    @staticmethod
    def is_available() -> bool:
        try:
            import litellm

            return True
        except ImportError:
            return False

    def patch_all_methods(self) -> None:
        import litellm

        self.method_patcher.register_patch(
            litellm,
            "completion",
            self._create_sync_wrapper(),
        )
        self.method_patcher.register_patch(
            litellm,
            "acompletion",
            self._create_async_wrapper(),
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
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError):
            return ""

    def apply_text_to_response(
        self, response: Any, new_text: str
    ) -> Any:
        response.choices[0].message.content = new_text
        return response

    def _create_sync_wrapper(self):
        provider = self

        def wrapper(*args, **kwargs):
            original = (
                provider.method_patcher.patch_targets[
                    0
                ].original_method
            )
            return provider.execute_llm_call_sync(
                original, *args, **kwargs
            )

        return wrapper

    def _create_async_wrapper(self):
        provider = self

        async def wrapper(*args, **kwargs):
            original = (
                provider.method_patcher.patch_targets[
                    1
                ].original_method
            )
            return await provider.execute_llm_call_async(
                original, *args, **kwargs
            )

        return wrapper
