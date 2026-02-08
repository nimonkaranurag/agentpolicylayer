"""
APL Test Suite — Shared Fixtures

Provides fake (in-process) implementations of every LLM provider SDK
so that instrumentation tests can run without real API keys or network
access.  All fakes return deterministic responses that the test
assertions can rely on.

Providers faked:
    - openai          (Completions / AsyncCompletions)
    - anthropic       (Messages / AsyncMessages)
    - litellm         (completion / acompletion)
    - langchain_core  (BaseChatModel.invoke / ainvoke)
    - ibm_watsonx_ai  (ModelInference.chat)
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is importable
# ---------------------------------------------------------------------------
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

# ---------------------------------------------------------------------------
# Deterministic content returned by each fake provider
# ---------------------------------------------------------------------------
OPENAI_RESPONSE_CONTENT = "Hello from OpenAI!"
ANTHROPIC_RESPONSE_CONTENT = "Hello from Anthropic!"
LITELLM_RESPONSE_CONTENT = "Hello from LiteLLM!"
LANGCHAIN_RESPONSE_CONTENT = "Hello from LangChain!"
WATSONX_RESPONSE_CONTENT = "Hello from WatsonX!"


# ============================================================================
# Fake OpenAI SDK
# ============================================================================


def _build_fake_openai():
    """Build a fake ``openai`` package with chat completions."""

    # --- Response objects ---------------------------------------------------
    @dataclass
    class _ChatMessage:
        role: str = "assistant"
        content: str = OPENAI_RESPONSE_CONTENT

    @dataclass
    class _Choice:
        index: int = 0
        message: _ChatMessage = field(
            default_factory=_ChatMessage
        )
        finish_reason: str = "stop"

    @dataclass
    class _ChatCompletion:
        id: str = field(
            default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:8]}"
        )
        choices: list = field(
            default_factory=lambda: [_Choice()]
        )
        model: str = "gpt-4"

    # --- Resources ----------------------------------------------------------
    class Completions:
        def create(self, *args, **kwargs):
            return _ChatCompletion()

    class AsyncCompletions:
        async def create(self, *args, **kwargs):
            return _ChatCompletion()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class OpenAI:
        def __init__(self, **kw):
            self.chat = Chat()

    class AsyncOpenAI:
        def __init__(self, **kw):
            self.chat = types.SimpleNamespace(
                completions=AsyncCompletions()
            )

    # --- Assemble modules ---------------------------------------------------
    openai_mod = types.ModuleType("openai")
    openai_mod.OpenAI = OpenAI
    openai_mod.AsyncOpenAI = AsyncOpenAI

    resources_mod = types.ModuleType("openai.resources")
    resources_chat_mod = types.ModuleType(
        "openai.resources.chat"
    )
    resources_chat_mod.Completions = Completions
    resources_chat_mod.AsyncCompletions = AsyncCompletions

    # Expose helper types so tests can build custom responses
    openai_mod._ChatCompletion = _ChatCompletion
    openai_mod._Choice = _Choice
    openai_mod._ChatMessage = _ChatMessage

    return {
        "openai": openai_mod,
        "openai.resources": resources_mod,
        "openai.resources.chat": resources_chat_mod,
    }


# ============================================================================
# Fake Anthropic SDK
# ============================================================================


def _build_fake_anthropic():
    """Build a fake ``anthropic`` package with messages API."""

    @dataclass
    class _TextBlock:
        type: str = "text"
        text: str = ANTHROPIC_RESPONSE_CONTENT

    @dataclass
    class _AnthropicMessage:
        id: str = field(
            default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}"
        )
        content: list = field(
            default_factory=lambda: [_TextBlock()]
        )
        model: str = "claude-sonnet-4-5-20250929"
        role: str = "assistant"

    class Messages:
        def create(self, *args, **kwargs):
            return _AnthropicMessage()

    class AsyncMessages:
        async def create(self, *args, **kwargs):
            return _AnthropicMessage()

    class Anthropic:
        def __init__(self, **kw):
            self.messages = Messages()

    class AsyncAnthropic:
        def __init__(self, **kw):
            self.messages = AsyncMessages()

    anthropic_mod = types.ModuleType("anthropic")
    anthropic_mod.Anthropic = Anthropic
    anthropic_mod.AsyncAnthropic = AsyncAnthropic

    resources_mod = types.ModuleType("anthropic.resources")
    resources_mod.Messages = Messages
    resources_mod.AsyncMessages = AsyncMessages

    anthropic_mod._AnthropicMessage = _AnthropicMessage
    anthropic_mod._TextBlock = _TextBlock

    return {
        "anthropic": anthropic_mod,
        "anthropic.resources": resources_mod,
    }


# ============================================================================
# Fake LiteLLM SDK
# ============================================================================


def _build_fake_litellm():
    """Build a fake ``litellm`` module."""

    @dataclass
    class _LLMsg:
        role: str = "assistant"
        content: str = LITELLM_RESPONSE_CONTENT

    @dataclass
    class _LLChoice:
        index: int = 0
        message: _LLMsg = field(default_factory=_LLMsg)
        finish_reason: str = "stop"

    @dataclass
    class _LLResponse:
        id: str = field(
            default_factory=lambda: f"ll-{uuid.uuid4().hex[:8]}"
        )
        choices: list = field(
            default_factory=lambda: [_LLChoice()]
        )
        model: str = "gpt-3.5-turbo"

    litellm_mod = types.ModuleType("litellm")

    def completion(*args, **kwargs):
        return _LLResponse()

    async def acompletion(*args, **kwargs):
        return _LLResponse()

    litellm_mod.completion = completion
    litellm_mod.acompletion = acompletion
    litellm_mod._LLResponse = _LLResponse
    litellm_mod._LLChoice = _LLChoice
    litellm_mod._LLMsg = _LLMsg

    return {"litellm": litellm_mod}


# ============================================================================
# Fake LangChain SDK
# ============================================================================


def _build_fake_langchain():
    """Build a fake ``langchain_core`` package."""

    @dataclass
    class AIMessage:
        content: str = LANGCHAIN_RESPONSE_CONTENT
        type: str = "ai"

    class BaseChatModel:
        model_name: str = "fake-chat-model"

        def invoke(self, input, config=None, **kwargs):
            return AIMessage()

        async def ainvoke(
            self, input, config=None, **kwargs
        ):
            return AIMessage()

    langchain_core = types.ModuleType("langchain_core")
    lm = types.ModuleType("langchain_core.language_models")
    cm = types.ModuleType(
        "langchain_core.language_models.chat_models"
    )
    cm.BaseChatModel = BaseChatModel

    langchain_core._AIMessage = AIMessage

    return {
        "langchain_core": langchain_core,
        "langchain_core.language_models": lm,
        "langchain_core.language_models.chat_models": cm,
    }


# ============================================================================
# Fake WatsonX SDK
# ============================================================================


def _build_fake_watsonx():
    """Build a fake ``ibm_watsonx_ai`` package."""

    ibm_watsonx_ai = types.ModuleType("ibm_watsonx_ai")
    foundation_models = types.ModuleType(
        "ibm_watsonx_ai.foundation_models"
    )

    class ModelInference:
        def __init__(self, model_id="test-model", **kw):
            self.model_id = model_id

        def chat(self, messages=None, **kwargs):
            return {
                "id": f"chat-{uuid.uuid4().hex[:8]}",
                "model_id": self.model_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": WATSONX_RESPONSE_CONTENT,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }

    foundation_models.ModelInference = ModelInference
    ibm_watsonx_ai.foundation_models = foundation_models

    return {
        "ibm_watsonx_ai": ibm_watsonx_ai,
        "ibm_watsonx_ai.foundation_models": foundation_models,
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def install_fake_providers(monkeypatch):
    """Install all fake provider SDKs into sys.modules for every test."""
    all_fakes = {}
    all_fakes.update(_build_fake_openai())
    all_fakes.update(_build_fake_anthropic())
    all_fakes.update(_build_fake_litellm())
    all_fakes.update(_build_fake_langchain())
    all_fakes.update(_build_fake_watsonx())

    for name, mod in all_fakes.items():
        monkeypatch.setitem(sys.modules, name, mod)

    yield


@pytest.fixture(autouse=True)
def clean_instrumentation():
    """Reset instrumentation state between tests."""
    yield
    import apl.instrument as inst

    # Uninstrument everything that was patched
    for module_name in list(inst._instrumented):
        inst._uninstrument_module(module_name)
    inst._instrumented.clear()
    inst._policy_layer = None
    inst._session_metadata = None
    inst._set_reentrant(False)


# ---------------------------------------------------------------------------
# Helpers available to all test modules
# ---------------------------------------------------------------------------


def make_event(
    event_type,
    messages=None,
    output_text=None,
    tool_name=None,
    tool_args=None,
    llm_model=None,
    token_count=0,
    token_budget=None,
    cost_usd=0.0,
    cost_budget_usd=None,
    user_roles=None,
):
    """Shortcut to build a ``PolicyEvent`` for testing."""
    from apl import (
        EventPayload,
    )
    from apl import EventType as ET
    from apl import (
        Message,
        PolicyEvent,
        SessionMetadata,
    )

    if isinstance(event_type, str):
        event_type = ET(event_type)

    msgs = []
    for m in messages or []:
        if isinstance(m, dict):
            msgs.append(
                Message(
                    role=m.get("role", "user"),
                    content=m.get("content"),
                )
            )
        else:
            msgs.append(m)

    return PolicyEvent(
        id=str(uuid.uuid4()),
        type=event_type,
        timestamp=datetime.utcnow(),
        messages=msgs,
        payload=EventPayload(
            output_text=output_text,
            tool_name=tool_name,
            tool_args=tool_args,
            llm_model=llm_model,
        ),
        metadata=SessionMetadata(
            session_id="test-session",
            token_count=token_count,
            token_budget=token_budget,
            cost_usd=cost_usd,
            cost_budget_usd=cost_budget_usd,
            user_roles=user_roles or [],
        ),
    )
