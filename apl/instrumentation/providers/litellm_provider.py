from __future__ import annotations

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
            self._create_module_sync_wrapper(),
        )
        self.method_patcher.register_patch(
            litellm,
            "acompletion",
            self._create_module_async_wrapper(),
        )
        self.method_patcher.apply_all_patches()

    def _create_module_sync_wrapper(self) -> Any:
        provider: LiteLLMProvider = self

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            original = (
                provider.method_patcher.patch_targets[
                    0
                ].original_method
            )
            return provider.execute_llm_call_sync(
                original, *args, **kwargs
            )

        return wrapper

    def _create_module_async_wrapper(self) -> Any:
        provider: LiteLLMProvider = self

        async def wrapper(
            *args: Any, **kwargs: Any
        ) -> Any:
            original = (
                provider.method_patcher.patch_targets[
                    1
                ].original_method
            )
            return (
                await provider.execute_llm_call_async(
                    original, *args, **kwargs
                )
            )

        return wrapper
