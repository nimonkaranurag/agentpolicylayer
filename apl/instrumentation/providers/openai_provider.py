from __future__ import annotations

from .base_provider import BaseProvider


class OpenAIProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "openai"

    @staticmethod
    def is_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("openai") is not None

    def patch_all_methods(self) -> None:
        from openai.resources.chat import AsyncCompletions, Completions

        self.method_patcher.register_patch(
            Completions, "create", self._sync_instance_factory()
        )
        self.method_patcher.register_patch(
            AsyncCompletions, "create", self._async_instance_factory()
        )
        self.method_patcher.apply_all_patches()
