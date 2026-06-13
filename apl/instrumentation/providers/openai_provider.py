from __future__ import annotations

from typing import Any

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

        # Responses API — its own resource and increasingly the default for new
        # apps. It bypasses chat.completions entirely, so without patching it
        # `client.responses.create(...)` ran no policies at all.
        try:
            from openai.resources.responses import AsyncResponses, Responses

            self.method_patcher.register_patch(
                Responses, "create", self._sync_instance_factory()
            )
            self.method_patcher.register_patch(
                AsyncResponses, "create", self._async_instance_factory()
            )
        except ImportError:
            # Older openai SDK without the Responses resource — nothing to patch.
            pass

        # Structured-output helper (`client.beta.chat.completions.parse`) calls
        # `_post` directly, never the patched chat.completions.create, so it was a
        # total bypass too. Same chat-completions response shape, so the default
        # extractors apply.
        try:
            from openai.resources.beta.chat.completions import (
                AsyncCompletions as AsyncBetaCompletions,
            )
            from openai.resources.beta.chat.completions import (
                Completions as BetaCompletions,
            )

            self.method_patcher.register_patch(
                BetaCompletions, "parse", self._sync_instance_factory()
            )
            self.method_patcher.register_patch(
                AsyncBetaCompletions, "parse", self._async_instance_factory()
            )
        except ImportError:
            pass

        self.method_patcher.apply_all_patches()

    # -- Request shape (chat.completions uses `messages`, Responses uses `input`) ---

    def extract_messages_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> Any:
        if "messages" in kwargs:
            return kwargs["messages"]
        # Responses API takes `input` (a string or a message list).
        return kwargs.get("input", [])

    def write_request_messages(self, args: Any, kwargs: Any, raw_messages: Any) -> Any:
        new_kwargs = dict(kwargs)
        if "input" in kwargs and "messages" not in kwargs:
            new_kwargs["input"] = raw_messages
        else:
            new_kwargs["messages"] = raw_messages
        return args, new_kwargs

    # -- Response shape (handle both ChatCompletion and Responses `Response`) -------

    def extract_text_from_response(self, response: Any) -> str:
        # Responses API exposes an aggregated `output_text` convenience.
        text = getattr(response, "output_text", None)
        if isinstance(text, str):
            return text
        return super().extract_text_from_response(response)

    def apply_text_to_response(self, response: Any, new_text: str) -> Any:
        # Responses API: text lives in output[].content[].text. Rewrite every text
        # part so the aggregated `output_text` reflects the modification.
        output = getattr(response, "output", None)
        if output is not None:
            applied = False
            for item in output:
                for part in getattr(item, "content", None) or []:
                    if hasattr(part, "text"):
                        part.text = new_text
                        applied = True
            if applied:
                return response
        return super().apply_text_to_response(response, new_text)

    def extract_chunk_text(self, chunk: Any) -> str:
        # Responses API streaming: ResponseTextDeltaEvent
        # (type="response.output_text.delta", delta="...").
        chunk_type = getattr(chunk, "type", "")
        if isinstance(chunk_type, str) and chunk_type.endswith("output_text.delta"):
            delta = getattr(chunk, "delta", "")
            return delta if isinstance(delta, str) else ""
        return super().extract_chunk_text(chunk)

    def apply_chunk_text(self, chunk: Any, new_text: str) -> None:
        chunk_type = getattr(chunk, "type", "")
        if isinstance(chunk_type, str) and chunk_type.endswith("output_text.delta"):
            try:
                chunk.delta = new_text
            except (AttributeError, TypeError):
                pass
            return
        super().apply_chunk_text(chunk, new_text)
