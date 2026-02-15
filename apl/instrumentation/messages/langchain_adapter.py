from typing import Any, List

from apl.types import Message

from .base_adapter import BaseMessageAdapter


class LangChainMessageAdapter(BaseMessageAdapter):

    LANGCHAIN_TYPE_TO_ROLE = {
        "human": "user",
        "ai": "assistant",
        "system": "system",
        "function": "tool",
        "tool": "tool",
    }

    def to_apl_messages(
        self, raw_input: Any
    ) -> List[Message]:
        if isinstance(raw_input, str):
            return [Message(role="user", content=raw_input)]

        if isinstance(raw_input, list):
            return [
                self._convert_langchain_message(msg)
                for msg in raw_input
            ]

        return []

    def _convert_langchain_message(
        self, langchain_message: Any
    ) -> Message:
        return Message(
            role=self._extract_role(langchain_message),
            content=self._extract_content(
                langchain_message
            ),
        )

    def _extract_role(self, langchain_message: Any) -> str:
        if isinstance(langchain_message, dict):
            return langchain_message.get("role", "user")
        if hasattr(langchain_message, "type"):
            return self.LANGCHAIN_TYPE_TO_ROLE.get(
                langchain_message.type, "user"
            )
        if hasattr(langchain_message, "role"):
            return langchain_message.role

        return "user"

    def _extract_content(
        self, langchain_message: Any
    ) -> str:
        if isinstance(langchain_message, dict):
            return langchain_message.get("content", "")
        if hasattr(langchain_message, "content"):
            return langchain_message.content

        return str(langchain_message)
