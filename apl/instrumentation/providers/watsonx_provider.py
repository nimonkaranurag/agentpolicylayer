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
        try:
            from ibm_watsonx_ai.foundation_models import (
                ModelInference,
            )

            return True
        except ImportError:
            return False

    def patch_all_methods(self) -> None:
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        self.method_patcher.register_patch(
            ModelInference,
            "chat",
            self._create_sync_wrapper(),
        )
        self.method_patcher.apply_all_patches()

    def extract_messages_from_request(
        self, *args, **kwargs
    ) -> Any:
        if "messages" in kwargs:
            return kwargs["messages"]
        if len(args) >= 1:
            return args[0]
        return []

    def extract_model_from_request(
        self, *args, **kwargs
    ) -> str:
        return "watsonx"

    def extract_text_from_response(
        self, response: Any
    ) -> str:
        try:
            return (
                response["choices"][0]["message"]["content"]
                or ""
            )
        except (KeyError, IndexError, TypeError):
            return ""

    def apply_text_to_response(
        self, response: Any, new_text: str
    ) -> Any:
        try:
            response["choices"][0]["message"][
                "content"
            ] = new_text
        except (KeyError, IndexError, TypeError):
            logger.warning(
                "Failed to apply modified text to WatsonX response"
            )
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
