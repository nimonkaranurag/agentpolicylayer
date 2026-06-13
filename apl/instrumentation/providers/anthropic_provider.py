from __future__ import annotations

from typing import Any

from .base_provider import BaseProvider


class AnthropicProvider(BaseProvider):
    """
    Instrumentation for the Anthropic SDK.

    Patches ``Messages.create`` / ``AsyncMessages.create`` — including
    ``create(stream=True)``, whose streamed ``content_block_delta`` events are enforced
    via :meth:`extract_chunk_text` / :meth:`apply_chunk_text` below.

    **Not patched (documented exclusion):** the ``client.messages.stream()`` *helper*.
    It returns a bespoke ``MessageStreamManager`` context manager (``with ... as
    stream``) with its own ``.text_stream`` / ``.get_final_message()`` surface rather
    than a plain iterable of chunks, so it can't be routed through the buffering
    enforcement path without re-implementing that API. Prefer ``create(stream=True)``
    when output policies must be enforced on a stream.
    """

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @staticmethod
    def is_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("anthropic") is not None

    def patch_all_methods(self) -> None:
        from anthropic.resources import (
            AsyncMessages,
            Messages,
        )

        self.method_patcher.register_patch(
            Messages, "create", self._sync_instance_factory()
        )
        self.method_patcher.register_patch(
            AsyncMessages, "create", self._async_instance_factory()
        )
        self.method_patcher.apply_all_patches()

    def extract_text_from_response(self, response: Any) -> str:
        try:
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
        except (AttributeError, IndexError):
            pass
        return ""

    def apply_text_to_response(self, response, new_text):
        try:
            response.content[0].text = new_text
        except (AttributeError, IndexError):
            pass
        return response

    def extract_chunk_text(self, chunk: Any) -> str:
        # Anthropic streams typed events; text rides on a ``content_block_delta``
        # event's ``.delta.text``. The base default reads the OpenAI
        # ``.choices[0].delta.content`` shape, which is always absent here — so
        # every chunk extracted "", the buffered output was empty, and the
        # output policy never saw (or could redact/deny) the streamed text.
        try:
            if getattr(chunk, "type", None) == "content_block_delta":
                return chunk.delta.text or ""
        except (AttributeError, IndexError, TypeError):
            pass
        return ""

    def apply_chunk_text(self, chunk: Any, new_text: str) -> None:
        try:
            if getattr(chunk, "type", None) == "content_block_delta":
                chunk.delta.text = new_text
        except (AttributeError, IndexError, TypeError):
            pass
