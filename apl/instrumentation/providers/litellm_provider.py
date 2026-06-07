from __future__ import annotations

from .base_provider import BaseProvider


class LiteLLMProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "litellm"

    @staticmethod
    def is_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("litellm") is not None

    def patch_all_methods(self) -> None:
        import litellm

        self.method_patcher.register_patch(
            litellm, "completion", self._sync_module_factory()
        )
        self.method_patcher.register_patch(
            litellm, "acompletion", self._async_module_factory()
        )
        self.method_patcher.apply_all_patches()
