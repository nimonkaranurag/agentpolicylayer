from __future__ import annotations

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
            self._create_instance_method_sync_wrapper(
                patch_target_index=0
            ),
        )
        self.method_patcher.register_patch(
            BaseChatModel,
            "ainvoke",
            self._create_instance_method_async_wrapper(
                patch_target_index=1
            ),
        )
        self.method_patcher.apply_all_patches()

    def extract_messages_from_request(
        self, *args: Any, **kwargs: Any
    ) -> Any:
        if len(args) >= 1:
            return args[0]
        return kwargs.get("input", [])

    def extract_model_from_request(
        self, *args: Any, **kwargs: Any
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
