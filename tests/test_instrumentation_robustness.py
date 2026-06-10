from __future__ import annotations

import asyncio
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
from apl.types import EventType, Verdict


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
