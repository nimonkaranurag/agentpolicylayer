from __future__ import annotations

from typing import Any

from apl.logging import get_logger

from .base_provider import BaseProvider

logger = get_logger("instrumentation.watsonx")


class WatsonXProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "watsonx"

    @staticmethod
    def is_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("ibm_watsonx_ai") is not None

    def patch_all_methods(self) -> None:
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        self.method_patcher.register_patch(
            ModelInference, "chat", self._sync_instance_factory()
        )
        # Async chat (``achat``) shipped in newer ibm-watsonx-ai; patch it only when the
        # installed SDK exposes it so older versions still instrument the sync path.
        if hasattr(ModelInference, "achat"):
            self.method_patcher.register_patch(
                ModelInference, "achat", self._async_instance_factory()
            )
        self.method_patcher.apply_all_patches()

    def extract_messages_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> Any:
        if "messages" in kwargs:
            return kwargs["messages"]
        if len(args) >= 1:
            return args[0]
        return []

    def write_request_messages(self, args: Any, kwargs: Any, raw_messages: Any) -> Any:
        # Mirror extract_messages_from_request: the messages= kwarg if present, else
        # the first positional argument.
        if "messages" in kwargs or len(args) < 1:
            new_kwargs = dict(kwargs)
            new_kwargs["messages"] = raw_messages
            return args, new_kwargs
        return (raw_messages, *args[1:]), kwargs

    def extract_model_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> str:
        # WatsonX binds the deployed model to the ModelInference instance.
        return getattr(instance, "model_id", None) or "watsonx"

    def extract_text_from_response(self, response: Any) -> str:
        try:
            return response["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""

    def apply_text_to_response(self, response: Any, new_text: str) -> Any:
        try:
            response["choices"][0]["message"]["content"] = new_text
        except (KeyError, IndexError, TypeError):
            logger.warning("Failed to apply modified text to WatsonX response")
        return response
