import uuid
from typing import Any

from apl.instrumentation.messages import (
    LangChainMessageAdapter,
)
from apl.types import Message, SessionMetadata


class LangGraphStateExtractor:

    def __init__(self):
        self._message_adapter = (
            LangChainMessageAdapter()
        )

    def extract_messages(
        self, state: Any
    ) -> list[Message]:
        raw_messages = (
            self._get_raw_messages_from_state(state)
        )
        if not raw_messages:
            return []
        return self._message_adapter.to_apl_messages(
            raw_messages
        )

    def extract_metadata(
        self, state: Any, config: dict | None
    ) -> SessionMetadata:
        session_id = str(uuid.uuid4())
        user_id = None

        if config:
            configurable = config.get(
                "configurable", {}
            )
            session_id = configurable.get(
                "thread_id", session_id
            )
            user_id = configurable.get("user_id")

        return SessionMetadata(
            session_id=session_id, user_id=user_id
        )

    def _get_raw_messages_from_state(
        self, state: Any
    ) -> list | None:
        if isinstance(state, dict):
            return (
                state.get("messages")
                or state.get("chat_history")
                or state.get("history")
            )
        elif isinstance(state, list):
            return state
        elif hasattr(state, "messages"):
            return state.messages
        return None
