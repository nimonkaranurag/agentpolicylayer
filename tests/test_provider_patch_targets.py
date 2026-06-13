from __future__ import annotations

import asyncio
import importlib.machinery
import sys
import types
from contextlib import contextmanager
from typing import Iterator

import pytest

from apl.instrumentation.providers.method_patcher import APL_PATCH_MARKER
from apl.instrumentation.state import InstrumentationState
from apl.layer import PolicyDenied, PolicyLayer
from apl.types import EventType, Verdict


# ---------------------------------------------------------------------------------------
# A policy layer that denies on output, so a single create()/chat()/completion() call
# proves the patched method actually drove the lifecycle (pre-request -> call -> extract
# response -> post-response -> enforce), not merely that an attribute was reassigned.
# ---------------------------------------------------------------------------------------
def _state_denying_output() -> InstrumentationState:
    layer = PolicyLayer()

    async def _evaluate(*, event_type, messages, payload, metadata):
        if event_type == EventType.OUTPUT_PRE_SEND:
            return Verdict.deny("blocked by patch-target test")
        return Verdict.allow()

    layer.evaluate = _evaluate
    return InstrumentationState(policy_layer=layer)


# ---------------------------------------------------------------------------------------
# Module-tree plumbing: install fake packages into sys.modules with real ModuleSpecs (so
# importlib.util.find_spec — used by every provider's is_available() — resolves them),
# then restore the prior state on exit.
# ---------------------------------------------------------------------------------------
def _module(name: str, *, is_package: bool = False) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(
        name, loader=None, is_package=is_package
    )
    if is_package:
        # A package needs a (possibly empty) search path; submodules are pre-installed
        # into sys.modules, so the path is never actually walked.
        module.__path__ = []  # type: ignore[attr-defined]
    return module


@contextmanager
def _install(tree: dict[str, types.ModuleType]) -> Iterator[None]:
    """
    Install ``tree`` (dotted-name -> module, listed parents-first) into sys.modules,
    wiring each child as an attribute of its parent, and restore the prior state on
    exit.
    """
    saved: dict[str, types.ModuleType | None] = {}
    try:
        for name, module in tree.items():
            saved[name] = sys.modules.get(name)
            sys.modules[name] = module
            if "." in name:
                parent, _, child = name.rpartition(".")
                setattr(sys.modules[parent], child, module)
        yield
    finally:
        for name in reversed(list(tree)):
            previous = saved[name]
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _chat_completion(text: str) -> types.SimpleNamespace:
    """
    A chat-completions-shaped response: ``response.choices[0].message.content``.
    """
    message = types.SimpleNamespace(content=text)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


_REQUEST = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}


# ---------------------------------------------------------------------------------------
# OpenAI: chat.completions + Responses + beta.chat.completions.parse
# ---------------------------------------------------------------------------------------
def _openai_tree() -> dict[str, types.ModuleType]:
    chat = _module("openai.resources.chat")

    class Completions:
        def create(self, **kwargs):
            return _chat_completion("openai-sync")

    class AsyncCompletions:
        async def create(self, **kwargs):
            return _chat_completion("openai-async")

    chat.Completions = Completions  # type: ignore[attr-defined]
    chat.AsyncCompletions = AsyncCompletions  # type: ignore[attr-defined]

    responses = _module("openai.resources.responses")

    class Responses:
        def create(self, **kwargs):
            return _chat_completion("responses-sync")

    class AsyncResponses:
        async def create(self, **kwargs):
            return _chat_completion("responses-async")

    responses.Responses = Responses  # type: ignore[attr-defined]
    responses.AsyncResponses = AsyncResponses  # type: ignore[attr-defined]

    beta_completions = _module("openai.resources.beta.chat.completions")

    class BetaCompletions:
        def parse(self, **kwargs):
            return _chat_completion("beta-parse-sync")

    class AsyncBetaCompletions:
        async def parse(self, **kwargs):
            return _chat_completion("beta-parse-async")

    beta_completions.Completions = BetaCompletions  # type: ignore[attr-defined]
    beta_completions.AsyncCompletions = AsyncBetaCompletions  # type: ignore[attr-defined]

    return {
        "openai": _module("openai", is_package=True),
        "openai.resources": _module("openai.resources", is_package=True),
        "openai.resources.chat": chat,
        "openai.resources.responses": responses,
        "openai.resources.beta": _module("openai.resources.beta", is_package=True),
        "openai.resources.beta.chat": _module(
            "openai.resources.beta.chat", is_package=True
        ),
        "openai.resources.beta.chat.completions": beta_completions,
    }


class TestOpenAIPatchTargets:
    def test_patch_all_methods_runs_against_sdk_shaped_module(self):
        from apl.instrumentation.providers.openai_provider import OpenAIProvider

        state = _state_denying_output()
        provider = OpenAIProvider(state)
        with _install(_openai_tree()):
            assert OpenAIProvider.is_available() is True
            provider.patch_all_methods()
            chat = sys.modules["openai.resources.chat"]
            responses = sys.modules["openai.resources.responses"]
            beta = sys.modules["openai.resources.beta.chat.completions"]
            try:
                # Every documented target was reached by the real import + registration.
                assert getattr(chat.Completions.create, APL_PATCH_MARKER, False)
                assert getattr(chat.AsyncCompletions.create, APL_PATCH_MARKER, False)
                assert getattr(responses.Responses.create, APL_PATCH_MARKER, False)
                assert getattr(responses.AsyncResponses.create, APL_PATCH_MARKER, False)
                assert getattr(beta.Completions.parse, APL_PATCH_MARKER, False)
                assert getattr(beta.AsyncCompletions.parse, APL_PATCH_MARKER, False)

                # A real call drives extract_text_from_response + enforcement.
                with pytest.raises(PolicyDenied):
                    chat.Completions().create(**_REQUEST)
                with pytest.raises(PolicyDenied):
                    asyncio.run(chat.AsyncCompletions().create(**_REQUEST))
            finally:
                provider.unpatch_all_methods()
                state.shutdown_background_loop()
            assert not getattr(chat.Completions.create, APL_PATCH_MARKER, False)


# ---------------------------------------------------------------------------------------
# Anthropic: Messages.create / AsyncMessages.create (response.content[0].text shape)
# ---------------------------------------------------------------------------------------
def _anthropic_tree() -> dict[str, types.ModuleType]:
    resources = _module("anthropic.resources", is_package=True)

    def _message(text: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=text)])

    class Messages:
        def create(self, **kwargs):
            return _message("anthropic-sync")

    class AsyncMessages:
        async def create(self, **kwargs):
            return _message("anthropic-async")

    resources.Messages = Messages  # type: ignore[attr-defined]
    resources.AsyncMessages = AsyncMessages  # type: ignore[attr-defined]

    return {
        "anthropic": _module("anthropic", is_package=True),
        "anthropic.resources": resources,
    }


class TestAnthropicPatchTargets:
    def test_patch_all_methods_runs_against_sdk_shaped_module(self):
        from apl.instrumentation.providers.anthropic_provider import AnthropicProvider

        state = _state_denying_output()
        provider = AnthropicProvider(state)
        with _install(_anthropic_tree()):
            assert AnthropicProvider.is_available() is True
            provider.patch_all_methods()
            resources = sys.modules["anthropic.resources"]
            try:
                assert getattr(resources.Messages.create, APL_PATCH_MARKER, False)
                assert getattr(resources.AsyncMessages.create, APL_PATCH_MARKER, False)
                with pytest.raises(PolicyDenied):
                    resources.Messages().create(**_REQUEST)
                with pytest.raises(PolicyDenied):
                    asyncio.run(resources.AsyncMessages().create(**_REQUEST))
            finally:
                provider.unpatch_all_methods()
                state.shutdown_background_loop()
            assert not getattr(resources.Messages.create, APL_PATCH_MARKER, False)


# ---------------------------------------------------------------------------------------
# LiteLLM: module-level completion / acompletion (the only module-function provider)
# ---------------------------------------------------------------------------------------
def _litellm_tree() -> dict[str, types.ModuleType]:
    litellm = _module("litellm", is_package=True)

    def completion(**kwargs):
        return _chat_completion("litellm-sync")

    async def acompletion(**kwargs):
        return _chat_completion("litellm-async")

    litellm.completion = completion  # type: ignore[attr-defined]
    litellm.acompletion = acompletion  # type: ignore[attr-defined]
    return {"litellm": litellm}


class TestLiteLLMPatchTargets:
    def test_patch_all_methods_runs_against_sdk_shaped_module(self):
        from apl.instrumentation.providers.litellm_provider import LiteLLMProvider

        state = _state_denying_output()
        provider = LiteLLMProvider(state)
        with _install(_litellm_tree()):
            assert LiteLLMProvider.is_available() is True
            provider.patch_all_methods()
            litellm = sys.modules["litellm"]
            try:
                assert getattr(litellm.completion, APL_PATCH_MARKER, False)
                assert getattr(litellm.acompletion, APL_PATCH_MARKER, False)
                with pytest.raises(PolicyDenied):
                    litellm.completion(**_REQUEST)
                with pytest.raises(PolicyDenied):
                    asyncio.run(litellm.acompletion(**_REQUEST))
            finally:
                provider.unpatch_all_methods()
                state.shutdown_background_loop()
            assert not getattr(litellm.completion, APL_PATCH_MARKER, False)


# ---------------------------------------------------------------------------------------
# WatsonX: ModelInference.chat / .achat (dict response shape; achat-present branch)
# ---------------------------------------------------------------------------------------
def _watsonx_tree() -> dict[str, types.ModuleType]:
    foundation_models = _module("ibm_watsonx_ai.foundation_models", is_package=True)

    def _response(text: str) -> dict:
        return {"choices": [{"message": {"content": text}}]}

    class ModelInference:
        model_id = "ibm/granite-13b"

        def chat(self, messages=None, **kwargs):
            return _response("watsonx-sync")

        async def achat(self, messages=None, **kwargs):
            return _response("watsonx-async")

    foundation_models.ModelInference = ModelInference  # type: ignore[attr-defined]
    return {
        "ibm_watsonx_ai": _module("ibm_watsonx_ai", is_package=True),
        "ibm_watsonx_ai.foundation_models": foundation_models,
    }


class TestWatsonXPatchTargets:
    def test_patch_all_methods_runs_against_sdk_shaped_module(self):
        from apl.instrumentation.providers.watsonx_provider import WatsonXProvider

        state = _state_denying_output()
        provider = WatsonXProvider(state)
        with _install(_watsonx_tree()):
            assert WatsonXProvider.is_available() is True
            provider.patch_all_methods()
            model_inference = sys.modules[
                "ibm_watsonx_ai.foundation_models"
            ].ModelInference
            try:
                # Both the sync chat and the newer-SDK achat branch were registered.
                assert getattr(model_inference.chat, APL_PATCH_MARKER, False)
                assert getattr(model_inference.achat, APL_PATCH_MARKER, False)
                with pytest.raises(PolicyDenied):
                    model_inference().chat(messages=_REQUEST["messages"])
                with pytest.raises(PolicyDenied):
                    asyncio.run(model_inference().achat(messages=_REQUEST["messages"]))
            finally:
                provider.unpatch_all_methods()
                state.shutdown_background_loop()
            assert not getattr(model_inference.chat, APL_PATCH_MARKER, False)

    def test_sync_only_sdk_skips_the_async_branch(self):
        # Older ibm-watsonx-ai exposes no `achat`; patch_all_methods must still
        # instrument the sync path and register exactly one target.
        from apl.instrumentation.providers.watsonx_provider import WatsonXProvider

        tree = _watsonx_tree()
        del tree["ibm_watsonx_ai.foundation_models"].ModelInference.achat

        state = _state_denying_output()
        provider = WatsonXProvider(state)
        with _install(tree):
            provider.patch_all_methods()
            try:
                names = {t.method_name for t in provider.method_patcher.patch_targets}
                assert names == {"chat"}
            finally:
                provider.unpatch_all_methods()
                state.shutdown_background_loop()
