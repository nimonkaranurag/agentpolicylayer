from __future__ import annotations

import asyncio
import importlib.util
import inspect
import types

import pytest

import apl.instrumentation as instrumentation
from apl.instrumentation.providers.base_provider import BaseProvider
from apl.instrumentation.providers.method_patcher import (
    APL_PATCH_MARKER,
    MethodPatcher,
)
from apl.instrumentation.state import InstrumentationState
from apl.layer import PolicyDenied, PolicyLayer
from apl.types import EventType, Message, Verdict

_HAS_LANGCHAIN = importlib.util.find_spec("langchain_core") is not None


# ---------------------------------------------------------------------------------------
# Fakes: a minimal chat-completions shaped SDK + a provider that instruments it.
# ---------------------------------------------------------------------------------------
def _completion(text: str) -> types.SimpleNamespace:
    """
    An object shaped like a chat-completions response (response.choices[0].message).
    """
    message = types.SimpleNamespace(content=text)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _chunk(text: str) -> types.SimpleNamespace:
    """
    An object shaped like a streamed chunk (chunk.choices[0].delta).
    """
    delta = types.SimpleNamespace(content=text)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


def _sync_client_cls(chunk_texts: list[str]):
    class _SyncClient:
        def create(self, **kwargs):
            if kwargs.get("stream"):
                return iter([_chunk(t) for t in chunk_texts])
            return _completion("".join(chunk_texts))

    return _SyncClient


def _async_client_cls(chunk_texts: list[str]):
    class _AsyncClient:
        async def create(self, **kwargs):
            if kwargs.get("stream"):

                async def _agen():
                    for text in chunk_texts:
                        yield _chunk(text)

                return _agen()
            return _completion("".join(chunk_texts))

    return _AsyncClient


class _FakeProvider(BaseProvider):
    """
    Instruments ``target_cls.create``, picking the factory by sync/async-ness.
    """

    def __init__(self, state: InstrumentationState, target_cls) -> None:
        self._target_cls = target_cls
        super().__init__(state)

    @property
    def provider_name(self) -> str:
        return "openai"  # reuse the chat-completions message adapter

    @staticmethod
    def is_available() -> bool:
        return True

    def patch_all_methods(self) -> None:
        create = self._target_cls.create
        if inspect.iscoroutinefunction(create):
            factory = self._async_instance_factory()
        else:
            factory = self._sync_instance_factory()
        self.method_patcher.register_patch(self._target_cls, "create", factory)
        self.method_patcher.apply_all_patches()


def _state_with_evaluate(evaluate) -> InstrumentationState:
    layer = PolicyLayer()
    layer.evaluate = evaluate
    return InstrumentationState(policy_layer=layer)


def _verdict_for(output_decider):
    """
    Build an async ``evaluate`` that allows everything except per ``output_decider``.
    """

    async def _evaluate(*, event_type, messages, payload, metadata):
        if event_type == EventType.OUTPUT_PRE_SEND:
            verdict = output_decider(payload)
            if verdict is not None:
                return verdict
        return Verdict.allow()

    return _evaluate


_REQUEST = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}


# ---------------------------------------------------------------------------------------
# idempotent / transactional / closure-captured patching
# ---------------------------------------------------------------------------------------
def _wrapping_factory(label: str):
    def factory(original):
        def wrapper(*args, **kwargs):
            return (label, original(*args, **kwargs))

        return wrapper

    return factory


class TestMethodPatcherIdempotency:
    def test_second_apply_does_not_capture_wrapper_as_original(self):
        class T:
            def m(self):
                return "orig"

        first = MethodPatcher()
        first.register_patch(T, "m", _wrapping_factory("a"))
        first.apply_all_patches()
        installed_wrapper = T.m
        assert getattr(T.m, APL_PATCH_MARKER, False) is True

        # A second instrumentation must be a no-op, not wrap the wrapper.
        second = MethodPatcher()
        second.register_patch(T, "m", _wrapping_factory("b"))
        second.apply_all_patches()
        assert T.m is installed_wrapper

        # Removing the second (which installed nothing) must not disturb the patch...
        second.remove_all_patches()
        assert T.m is installed_wrapper
        # ...and removing the first restores the *true* original, not a wrapper.
        first.remove_all_patches()
        assert T().m() == "orig"
        assert getattr(T.m, APL_PATCH_MARKER, False) is False

    def test_wrapper_exposes_real_original_via_functools_wraps(self):
        # OpenAI used to wrap a do-nothing stub, so the wrapper advertised the stub's name
        # and __wrapped__. The base factory now wraps the genuine original.
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        provider = _FakeProvider(state, _sync_client_cls([]))

        def original(self):  # noqa: ARG001 - signature stand-in
            return "orig"

        wrapper = provider._sync_instance_factory()(original)
        assert wrapper.__wrapped__ is original
        assert wrapper.__name__ == "original"

    def test_apply_all_patches_rolls_back_on_failure(self):
        class Good:
            def m(self):
                return "good"

        class Bad:
            def m(self):
                return "bad"

        def exploding_factory(original):
            raise RuntimeError("cannot build wrapper")

        patcher = MethodPatcher()
        patcher.register_patch(Good, "m", _wrapping_factory("g"))
        patcher.register_patch(Bad, "m", exploding_factory)

        good_original = Good.m
        with pytest.raises(RuntimeError):
            patcher.apply_all_patches()

        # Good was installed first, then rolled back when the second patch raised.
        assert Good.m is good_original
        assert Good().m() == "good"
        assert getattr(Good.m, APL_PATCH_MARKER, False) is False


# ---------------------------------------------------------------------------------------
# streaming is intercepted (output policies run, and can block)
# ---------------------------------------------------------------------------------------
class TestStreamingInterception:
    def test_sync_stream_output_policy_sees_full_text_and_can_block(self):
        seen = {}

        def decider(payload):
            text = payload.output_text or ""
            seen["text"] = text
            return Verdict.deny("secret leaked") if "secret" in text else None

        state = _state_with_evaluate(_verdict_for(decider))
        provider = _FakeProvider(state, _sync_client_cls(["my ", "secret", " token"]))
        provider.patch_all_methods()
        client = provider._target_cls()
        try:
            with pytest.raises(PolicyDenied):
                client.create(stream=True, **_REQUEST)
            # The policy evaluated against the *assembled* stream, not "".
            assert seen["text"] == "my secret token"
        finally:
            state.shutdown_background_loop()

    def test_sync_stream_allow_reemits_chunks(self):
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        provider = _FakeProvider(state, _sync_client_cls(["Hel", "lo"]))
        provider.patch_all_methods()
        client = provider._target_cls()
        try:
            result = client.create(stream=True, **_REQUEST)
            text = "".join(c.choices[0].delta.content for c in result)
            assert text == "Hello"
        finally:
            state.shutdown_background_loop()

    def test_sync_stream_modify_rewrites_emitted_text(self):
        def decider(payload):
            return Verdict.modify(
                target="output", operation="replace", value="[REDACTED]"
            )

        state = _state_with_evaluate(_verdict_for(decider))
        provider = _FakeProvider(state, _sync_client_cls(["se", "cret"]))
        provider.patch_all_methods()
        client = provider._target_cls()
        try:
            result = client.create(stream=True, **_REQUEST)
            text = "".join(c.choices[0].delta.content for c in result)
            assert text == "[REDACTED]"
        finally:
            state.shutdown_background_loop()

    def test_async_stream_output_policy_sees_full_text_and_can_block(self):
        seen = {}

        def decider(payload):
            text = payload.output_text or ""
            seen["text"] = text
            return Verdict.deny("secret leaked") if "secret" in text else None

        state = _state_with_evaluate(_verdict_for(decider))
        provider = _FakeProvider(state, _async_client_cls(["a ", "secret", "!"]))
        provider.patch_all_methods()
        client = provider._target_cls()

        async def _run():
            stream = await client.create(stream=True, **_REQUEST)
            return [chunk async for chunk in stream]

        with pytest.raises(PolicyDenied):
            asyncio.run(_run())
        assert seen["text"] == "a secret!"

    def test_async_stream_allow_reemits_chunks(self):
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        provider = _FakeProvider(state, _async_client_cls(["Hel", "lo"]))
        provider.patch_all_methods()
        client = provider._target_cls()

        async def _run():
            stream = await client.create(stream=True, **_REQUEST)
            return "".join([c.choices[0].delta.content async for c in stream])

        assert asyncio.run(_run()) == "Hello"

    def test_non_streaming_path_still_enforces(self):
        def decider(payload):
            text = payload.output_text or ""
            return Verdict.deny("blocked") if "secret" in text else None

        state = _state_with_evaluate(_verdict_for(decider))
        provider = _FakeProvider(state, _sync_client_cls(["a secret value"]))
        provider.patch_all_methods()
        client = provider._target_cls()
        try:
            with pytest.raises(PolicyDenied):
                client.create(**_REQUEST)
        finally:
            state.shutdown_background_loop()


class TestAlwaysStreamingEntryPoints:
    # `.stream()`/`.astream()` are *always* streaming (no `stream=` kwarg to
    # detect), so they get dedicated wrappers. Without them a streamed response
    # fell through the non-streaming branch and the output policy never ran.

    def _provider_patching(self, model_cls, method, factory_name):
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        provider = _FakeProvider(state, model_cls)
        provider.method_patcher.register_patch(
            model_cls, method, getattr(provider, factory_name)()
        )
        provider.method_patcher.apply_all_patches()
        return state, provider

    def test_sync_stream_method_is_enforced_and_reemits(self):
        class _Model:
            def stream(self, *a, **kw):
                return iter([_chunk("Hel"), _chunk("lo")])

        state, provider = self._provider_patching(
            _Model, "stream", "_sync_stream_instance_factory"
        )
        try:
            text = "".join(
                c.choices[0].delta.content for c in _Model().stream(**_REQUEST)
            )
            assert text == "Hello"
        finally:
            provider.method_patcher.remove_all_patches()
            state.shutdown_background_loop()

    def test_sync_stream_method_can_block(self):
        def decider(payload):
            return (
                Verdict.deny("x") if "secret" in (payload.output_text or "") else None
            )

        class _Model:
            def stream(self, *a, **kw):
                return iter([_chunk("se"), _chunk("cret")])

        state = _state_with_evaluate(_verdict_for(decider))
        provider = _FakeProvider(state, _Model)
        provider.method_patcher.register_patch(
            _Model, "stream", provider._sync_stream_instance_factory()
        )
        provider.method_patcher.apply_all_patches()
        try:
            with pytest.raises(PolicyDenied):
                list(_Model().stream(**_REQUEST))
        finally:
            provider.method_patcher.remove_all_patches()
            state.shutdown_background_loop()

    def test_async_stream_method_is_enforced(self):
        class _Model:
            def astream(self, *a, **kw):
                async def gen():
                    for token in ["Hel", "lo"]:
                        yield _chunk(token)

                return gen()

        state, provider = self._provider_patching(
            _Model, "astream", "_async_stream_instance_factory"
        )

        async def run():
            return "".join(
                [c.choices[0].delta.content async for c in _Model().astream(**_REQUEST)]
            )

        try:
            assert asyncio.run(run()) == "Hello"
        finally:
            provider.method_patcher.remove_all_patches()


class TestRequestModifyThroughExecutor:
    # End-to-end: a pre-request MODIFY of llm_prompt must reach the SDK call as
    # native chat-completions dicts in the slot it reads — not foreign-typed APL
    # Message objects, and not a kwarg the SDK ignores.
    def test_llm_prompt_modify_rewrites_native_messages(self):
        captured: dict = {}

        class _Client:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _completion("ok")

        async def evaluate(*, event_type, messages, payload, metadata):
            if event_type == EventType.LLM_PRE_REQUEST:
                return Verdict.modify(
                    target="llm_prompt",
                    operation="replace",
                    value=[Message(role="user", content="REDACTED")],
                )
            return Verdict.allow()

        state = _state_with_evaluate(evaluate)
        provider = _FakeProvider(state, _Client)
        provider.patch_all_methods()
        try:
            _Client().create(**_REQUEST)
            assert captured["messages"] == [{"role": "user", "content": "REDACTED"}]
        finally:
            provider.method_patcher.remove_all_patches()
            state.shutdown_background_loop()


# ---------------------------------------------------------------------------------------
# reentrancy guard isolated per async task (contextvars, not threading.local)
# ---------------------------------------------------------------------------------------
class TestReentrancyIsolation:
    def test_flag_is_isolated_per_async_task(self):
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        seen = {}

        async def marker():
            state.mark_policy_evaluation_started()
            await asyncio.sleep(0.02)
            seen["marker"] = state.is_inside_policy_evaluation()
            state.mark_policy_evaluation_finished()

        async def observer():
            await asyncio.sleep(0.01)  # runs while marker holds the flag
            seen["observer"] = state.is_inside_policy_evaluation()

        async def _run():
            await asyncio.gather(marker(), observer())

        asyncio.run(_run())
        assert seen["marker"] is True
        # With threading.local both tasks share the thread and observer sees True.
        assert seen["observer"] is False

    def test_flag_defaults_false_and_round_trips(self):
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        assert state.is_inside_policy_evaluation() is False
        state.mark_policy_evaluation_started()
        assert state.is_inside_policy_evaluation() is True
        state.mark_policy_evaluation_finished()
        assert state.is_inside_policy_evaluation() is False


# ---------------------------------------------------------------------------------------
# Background-loop shutdown
# ---------------------------------------------------------------------------------------
class TestBackgroundLoopShutdown:
    def test_shutdown_stops_thread_and_closes_loop(self):
        state = _state_with_evaluate(_verdict_for(lambda p: None))

        async def _answer():
            return 42

        assert state.run_coroutine_in_background_loop(_answer()) == 42
        loop = state._background_loop
        thread = state._background_thread
        assert loop is not None and loop.is_running()
        assert thread is not None and thread.is_alive()

        state.shutdown_background_loop()

        assert state._background_loop is None
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert not loop.is_running()

    def test_shutdown_is_safe_without_a_loop(self):
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        # Never started a loop; must not raise.
        state.shutdown_background_loop()
        assert state._background_loop is None

    def test_uninstrument_tears_down_background_loop(self):
        state = _state_with_evaluate(_verdict_for(lambda p: None))

        async def _answer():
            return 1

        state.run_coroutine_in_background_loop(_answer())
        thread = state._background_thread
        assert thread is not None and thread.is_alive()

        instrumentation.uninstrument(state)

        assert state._background_loop is None
        thread.join(timeout=2)
        assert not thread.is_alive()


# ---------------------------------------------------------------------------------------
# Provider drift — real model names + watsonx async surface
# ---------------------------------------------------------------------------------------
class TestProviderDrift:
    def test_langchain_reads_model_from_instance(self):
        from apl.instrumentation.providers.langchain_provider import LangChainProvider

        state = _state_with_evaluate(_verdict_for(lambda p: None))
        provider = LangChainProvider(state)
        chat_model = types.SimpleNamespace(model_name="claude-3-5-sonnet")
        assert (
            provider.extract_model_from_request(chat_model, {"input": []})
            == "claude-3-5-sonnet"
        )

    def test_watsonx_reads_model_id_from_instance(self):
        from apl.instrumentation.providers.watsonx_provider import WatsonXProvider

        state = _state_with_evaluate(_verdict_for(lambda p: None))
        provider = WatsonXProvider(state)
        inference = types.SimpleNamespace(model_id="ibm/granite-13b")
        assert provider.extract_model_from_request(inference) == "ibm/granite-13b"

    def test_watsonx_writes_request_messages_to_its_slot(self):
        from apl.instrumentation.providers.watsonx_provider import WatsonXProvider

        provider = WatsonXProvider.__new__(WatsonXProvider)
        # messages kwarg when present...
        _, kwargs = provider.write_request_messages((), {"messages": []}, [{"r": 1}])
        assert kwargs["messages"] == [{"r": 1}]
        # ...else the first positional argument.
        args, _ = provider.write_request_messages(("orig",), {}, [{"r": 2}])
        assert args[0] == [{"r": 2}]

    def test_watsonx_registers_async_patch_when_sdk_exposes_achat(self):
        from apl.instrumentation.providers.watsonx_provider import WatsonXProvider

        state = _state_with_evaluate(_verdict_for(lambda p: None))
        provider = WatsonXProvider(state)

        class _ModelInference:
            def chat(self):  # pragma: no cover - not invoked
                return None

            async def achat(self):  # pragma: no cover - not invoked
                return None

        provider.method_patcher.register_patch(
            _ModelInference, "chat", provider._sync_instance_factory()
        )
        if hasattr(_ModelInference, "achat"):
            provider.method_patcher.register_patch(
                _ModelInference, "achat", provider._async_instance_factory()
            )
        names = {t.method_name for t in provider.method_patcher.patch_targets}
        assert names == {"chat", "achat"}


class TestProviderStreamingAndEntryPointShapes:
    # The provider-specific shapes — exactly what breaks on an SDK release and
    # where the streaming/entry-point bypasses lived — exercised against
    # shape-faithful fakes (the real SDKs aren't installed in CI).

    def _provider(self, cls):
        state = _state_with_evaluate(_verdict_for(lambda p: None))
        return cls(state)

    def test_anthropic_extracts_content_block_delta(self):
        from apl.instrumentation.providers.anthropic_provider import AnthropicProvider

        provider = self._provider(AnthropicProvider)
        delta = types.SimpleNamespace(text="hello")
        chunk = types.SimpleNamespace(type="content_block_delta", delta=delta)
        assert provider.extract_chunk_text(chunk) == "hello"
        # An OpenAI-shaped chunk must NOT be read as Anthropic text.
        assert provider.extract_chunk_text(_chunk("x")) == ""

    def test_openai_extracts_responses_api_output_text(self):
        from apl.instrumentation.providers.openai_provider import OpenAIProvider

        provider = self._provider(OpenAIProvider)
        response = types.SimpleNamespace(output_text="responses-api text")
        assert provider.extract_text_from_response(response) == "responses-api text"
        # Still handles the chat-completions shape.
        assert provider.extract_text_from_response(_completion("chat text")) == (
            "chat text"
        )

    def test_openai_extracts_responses_streaming_delta(self):
        from apl.instrumentation.providers.openai_provider import OpenAIProvider

        provider = self._provider(OpenAIProvider)
        event = types.SimpleNamespace(type="response.output_text.delta", delta="bit")
        assert provider.extract_chunk_text(event) == "bit"

    def test_langchain_reads_chunk_content(self):
        from apl.instrumentation.providers.langchain_provider import LangChainProvider

        provider = self._provider(LangChainProvider)
        assert provider.extract_chunk_text(types.SimpleNamespace(content="tok")) == (
            "tok"
        )

    @pytest.mark.skipif(not _HAS_LANGCHAIN, reason="langchain_core not installed")
    def test_langchain_stream_and_astream_are_patched(self):
        from langchain_core.language_models.chat_models import BaseChatModel

        from apl.instrumentation.providers.langchain_provider import LangChainProvider

        provider = self._provider(LangChainProvider)
        provider.patch_all_methods()
        try:
            assert getattr(BaseChatModel.stream, APL_PATCH_MARKER, False)
            assert getattr(BaseChatModel.astream, APL_PATCH_MARKER, False)
        finally:
            provider.unpatch_all_methods()
        assert not getattr(BaseChatModel.stream, APL_PATCH_MARKER, False)
