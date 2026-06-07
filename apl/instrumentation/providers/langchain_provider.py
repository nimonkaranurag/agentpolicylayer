from __future__ import annotations

from typing import Any

from .base_provider import BaseProvider


class LangChainProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "langchain"

    @staticmethod
    def is_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("langchain_core") is not None

    def patch_all_methods(self) -> None:
        from langchain_core.language_models.chat_models import (
            BaseChatModel,
        )

        self.method_patcher.register_patch(
            BaseChatModel, "invoke", self._sync_instance_factory()
        )
        self.method_patcher.register_patch(
            BaseChatModel, "ainvoke", self._async_instance_factory()
        )
        self.method_patcher.apply_all_patches()

    def extract_messages_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> Any:
        if len(args) >= 1:
            return args[0]
        return kwargs.get("input", [])

    def extract_model_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> str:
        # The model identity lives on the chat-model instance, not the call kwargs.
        model = getattr(instance, "model_name", None) or getattr(
            instance, "model", None
        )
        return model or "langchain"

    def extract_text_from_response(self, response: Any) -> str:
        if hasattr(response, "content"):
            return response.content
        return str(response)

    def apply_text_to_response(self, response: Any, new_text: str) -> Any:
        response.content = new_text
        return response
