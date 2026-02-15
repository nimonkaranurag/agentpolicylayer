from typing import Any

from .base_provider import BaseProvider


class LangChainProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "langchain"

    @staticmethod
    def is_available() -> bool:
        try:
            from langchain_core.language_models.chat_models import (
                BaseChatModel,
            )

            return True
        except ImportError:
            return False

    def patch_all_methods(self) -> None:
        from langchain_core.language_models.chat_models import (
            BaseChatModel,
        )

        self.method_patcher.register_patch(
            BaseChatModel,
            "invoke",
            self._create_sync_wrapper(),
        )
        self.method_patcher.register_patch(
            BaseChatModel,
            "ainvoke",
            self._create_async_wrapper(),
        )
        self.method_patcher.apply_all_patches()

    def extract_messages_from_request(
        self, *args, **kwargs
    ) -> Any:
        if len(args) >= 1:
            return args[0]
        return kwargs.get("input", [])

    def extract_model_from_request(
        self, *args, **kwargs
    ) -> str:
        return "langchain"

    def extract_text_from_response(
        self, response: Any
    ) -> str:
        if hasattr(response, "content"):
            return response.content
        return str(response)

    def apply_text_to_response(
        self, response: Any, new_text: str
    ) -> Any:
        response.content = new_text
        return response

    def _create_sync_wrapper(self):
        provider = self

        def wrapper(model_self, *args, **kwargs):
            original = (
                provider.method_patcher.patch_targets[
                    0
                ].original_method
            )
            bound_method = lambda *a, **kw: original(
                model_self, *a, **kw
            )
            return provider.execute_llm_call_sync(
                bound_method, *args, **kwargs
            )

        return wrapper

    def _create_async_wrapper(self):
        provider = self

        async def wrapper(model_self, *args, **kwargs):
            original = (
                provider.method_patcher.patch_targets[
                    1
                ].original_method
            )

            async def bound_method(*a, **kw):
                return await original(model_self, *a, **kw)

            return await provider.execute_llm_call_async(
                bound_method, *args, **kwargs
            )

        return wrapper
