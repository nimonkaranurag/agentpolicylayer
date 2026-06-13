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
        # `.stream()` / `.astream()` are always-streaming entry points (no `stream`
        # kwarg to detect); a streaming-capable model routes through these, never the
        # patched invoke(), so without patching them policies never ran on a streamed
        # LangChain response.
        self.method_patcher.register_patch(
            BaseChatModel, "stream", self._sync_stream_instance_factory()
        )
        self.method_patcher.register_patch(
            BaseChatModel, "astream", self._async_stream_instance_factory()
        )
        self.method_patcher.apply_all_patches()

    def extract_messages_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> Any:
        if len(args) >= 1:
            return args[0]
        return kwargs.get("input", [])

    def write_request_messages(self, args: Any, kwargs: Any, raw_messages: Any) -> Any:
        # invoke()/stream() take the prompt *positionally* (input is args[0]); writing
        # a messages= kwarg (the base default) is silently ignored, so an input
        # redaction was a no-op. Write back to the slot the call actually reads.
        if len(args) >= 1:
            return (raw_messages, *args[1:]), kwargs
        new_kwargs = dict(kwargs)
        new_kwargs["input"] = raw_messages
        return args, new_kwargs

    def extract_chunk_text(self, chunk: Any) -> str:
        # LangChain streams BaseMessageChunk objects carrying text on `.content`.
        content = getattr(chunk, "content", None)
        return content if isinstance(content, str) else ""

    def apply_chunk_text(self, chunk: Any, new_text: str) -> None:
        try:
            chunk.content = new_text
        except (AttributeError, TypeError):
            # Best-effort: a chunk whose `content` isn't writable (immutable or a
            # non-text message chunk) is left unchanged.
            pass

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
