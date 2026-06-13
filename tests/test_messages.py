from __future__ import annotations

import importlib.util

import pytest

from apl.instrumentation.messages import (
    get_message_adapter,
)
from apl.instrumentation.messages.chat_completions_adapter import (
    ChatCompletionsMessageAdapter,
)
from apl.instrumentation.messages.langchain_adapter import (
    LangChainMessageAdapter,
)
from apl.types import Message

_HAS_LANGCHAIN = importlib.util.find_spec("langchain_core") is not None


class TestChatCompletionsAdapter:
    def setup_method(self):
        self.adapter = ChatCompletionsMessageAdapter()

    def test_dict_messages(self):
        raw = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = self.adapter.to_apl_messages(raw)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].content == "hello"

    def test_apl_messages_passthrough(self):
        raw = [Message(role="user", content="already apl")]
        result = self.adapter.to_apl_messages(raw)
        assert len(result) == 1
        assert result[0].content == "already apl"

    def test_empty_list(self):
        assert self.adapter.to_apl_messages([]) == []

    def test_non_list_returns_empty(self):
        assert self.adapter.to_apl_messages("not a list") == []

    def test_from_apl_messages(self):
        msgs = [Message(role="user", content="hi")]
        result = self.adapter.from_apl_messages(msgs)
        assert result == [{"role": "user", "content": "hi"}]

    def test_multipart_content_extraction(self):
        raw = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Look at this",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": "..."},
                    },
                ],
            }
        ]
        result = self.adapter.to_apl_messages(raw)
        assert result[0].content == "Look at this"


class TestLangChainAdapter:
    def setup_method(self):
        self.adapter = LangChainMessageAdapter()

    def test_string_input(self):
        result = self.adapter.to_apl_messages("hello")
        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].content == "hello"

    def test_dict_messages(self):
        raw = [{"role": "user", "content": "test"}]
        result = self.adapter.to_apl_messages(raw)
        assert result[0].role == "user"

    def test_empty_input(self):
        assert self.adapter.to_apl_messages([]) == []
        assert self.adapter.to_apl_messages(42) == []

    def test_from_apl_messages(self):
        msgs = [Message(role="assistant", content="response")]
        result = self.adapter.from_apl_messages(msgs)
        assert result == [
            {
                "role": "assistant",
                "content": "response",
            }
        ]

    def test_langchain_message_object(self):
        class FakeLCMessage:
            type = "human"
            content = "hello from langchain"

        result = self.adapter.to_apl_messages([FakeLCMessage()])
        assert result[0].role == "user"
        assert result[0].content == "hello from langchain"

    @pytest.mark.skipif(not _HAS_LANGCHAIN, reason="langchain_core not installed")
    def test_real_langchain_message_types(self):
        # The rest of this file's LangChain coverage uses a hand-rolled FakeLCMessage;
        # exercise the adapter against the *real* SDK classes so a drift in
        # langchain_core's BaseMessage.type/.content contract is actually caught (the
        # `.type` -> role mapping is the load-bearing line).
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        result = self.adapter.to_apl_messages(
            [
                SystemMessage(content="be brief"),
                HumanMessage(content="hi"),
                AIMessage(content="hello"),
            ]
        )
        assert [(m.role, m.content) for m in result] == [
            ("system", "be brief"),
            ("user", "hi"),
            ("assistant", "hello"),
        ]


class TestGetMessageAdapter:
    def test_openai_adapter(self):
        adapter = get_message_adapter("openai")
        assert isinstance(adapter, ChatCompletionsMessageAdapter)

    def test_litellm_adapter(self):
        adapter = get_message_adapter("litellm")
        assert isinstance(adapter, ChatCompletionsMessageAdapter)

    def test_anthropic_adapter(self):
        adapter = get_message_adapter("anthropic")
        assert isinstance(adapter, ChatCompletionsMessageAdapter)

    def test_langchain_adapter(self):
        adapter = get_message_adapter("langchain")
        assert isinstance(adapter, LangChainMessageAdapter)
