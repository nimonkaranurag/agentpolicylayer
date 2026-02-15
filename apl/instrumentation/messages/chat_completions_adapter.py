from typing import Any, List

from apl.types import Message

from .base_adapter import BaseMessageAdapter


class ChatCompletionsMessageAdapter(BaseMessageAdapter):

    def to_apl_messages(
        self, raw_messages: Any
    ) -> List[Message]:
        if not isinstance(raw_messages, list):
            return []

        return [
            self._convert_single_message(msg)
            for msg in raw_messages
            if self._convert_single_message(msg) is not None
        ]

    def _convert_single_message(
        self, raw_message: Any
    ) -> Message | None:
        if isinstance(raw_message, dict):
            return Message(
                role=raw_message.get("role", "user"),
                content=self._extract_content_text(
                    raw_message.get("content")
                ),
            )

        if isinstance(raw_message, Message):
            return raw_message

        if hasattr(raw_message, "role") and hasattr(
            raw_message, "content"
        ):
            return Message(
                role=raw_message.role,
                content=self._extract_content_text(
                    raw_message.content
                ),
            )

        return None

    def _extract_content_text(
        self, content: Any
    ) -> str | None:
        if content is None:
            return None

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
            ]
            return (
                "".join(text_parts) if text_parts else None
            )

        return str(content)
