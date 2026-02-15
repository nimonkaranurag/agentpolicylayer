import functools
from typing import Any

from .base_provider import BaseProvider


class OpenAIProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "openai"

    @staticmethod
    def is_available() -> bool:
        try:
            import openai

            return True
        except ImportError:
            return False

    def patch_all_methods(self) -> None:
        from openai.resources.chat import (
            AsyncCompletions,
            Completions,
        )

        self.method_patcher.register_patch(
            Completions,
            "create",
            self._create_sync_wrapper(),
        )
        self.method_patcher.register_patch(
            AsyncCompletions,
            "create",
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
        original_method = None

        @functools.wraps(self._get_sync_original)
        def wrapper(client_self, *args, **kwargs):
            nonlocal original_method
            if original_method is None:
                original_method = provider.method_patcher.get_original_method(
                    "create"
                )
            bound_method = lambda *a, **kw: original_method(
                client_self, *a, **kw
            )
            return provider.execute_llm_call_sync(
                bound_method, *args, **kwargs
            )

        return wrapper

    def _create_async_wrapper(self):
        provider = self
        original_method = None

        @functools.wraps(self._get_async_original)
        async def wrapper(client_self, *args, **kwargs):
            nonlocal original_method
            if original_method is None:
                original_method = provider.method_patcher.get_original_method(
                    "create"
                )

            async def bound_method(*a, **kw):
                return await original_method(
                    client_self, *a, **kw
                )

            return await provider.execute_llm_call_async(
                bound_method, *args, **kwargs
            )

        return wrapper

    def _get_sync_original(self):
        pass

    def _get_async_original(self):
        pass
