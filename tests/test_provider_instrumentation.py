"""
APL Provider Instrumentation Tests

Verifies that ``apl.auto_instrument()`` correctly monkey-patches every
supported LLM provider and that APL policies (DENY / MODIFY / ALLOW /
ESCALATE) are enforced through the wrapped call paths.

Providers under test:
    - OpenAI       (sync ``Completions.create``, async ``AsyncCompletions.create``)
    - Anthropic    (sync ``Messages.create``, async ``AsyncMessages.create``)
    - LiteLLM      (sync ``completion``, async ``acompletion``)
    - LangChain    (sync ``BaseChatModel.invoke``, async ``ainvoke``)
    - WatsonX      (sync ``ModelInference.chat``)

All tests run against fake (in-process) SDK stubs provided by ``conftest.py``
so no network access or API keys are required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

import apl
import apl.instrument as inst
from apl import Decision, Verdict
from apl.instrument import _instrumented
from apl.layer import PolicyDenied, PolicyEscalation
from tests.conftest import (
    ANTHROPIC_RESPONSE_CONTENT,
    LANGCHAIN_RESPONSE_CONTENT,
    LITELLM_RESPONSE_CONTENT,
    OPENAI_RESPONSE_CONTENT,
    WATSONX_RESPONSE_CONTENT,
)

# ============================================================================
# Helpers
# ============================================================================


def _auto(*, only: str):
    """Instrument only *one* provider so tests stay isolated."""
    flags = {
        "instrument_openai": only == "openai",
        "instrument_anthropic": only == "anthropic",
        "instrument_litellm": only == "litellm",
        "instrument_langchain": only == "langchain",
        "instrument_watsonx": only == "watsonx",
    }
    return apl.auto_instrument(policy_servers=[], **flags)


# ============================================================================
# OpenAI
# ============================================================================


class TestOpenAIInstrumentation:
    """Verify OpenAI ``Completions.create`` / ``AsyncCompletions.create``."""

    def _get_classes(self):
        from openai.resources.chat import (
            AsyncCompletions,
            Completions,
        )

        return Completions, AsyncCompletions

    # -- patch / unpatch -----------------------------------------------------

    def test_instrument_patches_create(self):
        Comp, AComp = self._get_classes()
        orig_sync = Comp.create
        orig_async = AComp.create

        _auto(only="openai")

        assert "openai" in _instrumented
        assert Comp.create is not orig_sync
        assert AComp.create is not orig_async

    def test_uninstrument_restores(self):
        Comp, AComp = self._get_classes()
        orig_sync = Comp.create

        _auto(only="openai")
        apl.uninstrument()

        assert Comp.create is orig_sync
        assert "openai" not in _instrumented

    def test_idempotent(self):
        _auto(only="openai")
        _auto(only="openai")  # second call is a no-op
        assert _instrumented == {"openai"}

    # -- verdict enforcement (sync) ------------------------------------------

    def test_allow_passes_through(self):
        _auto(only="openai")
        from openai import OpenAI

        client = OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert (
            resp.choices[0].message.content
            == OPENAI_RESPONSE_CONTENT
        )

    def test_deny_at_pre_request(self):
        _auto(only="openai")
        deny = Verdict.deny(reasoning="blocked")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=deny,
        ):
            from openai import OpenAI

            client = OpenAI()
            with pytest.raises(PolicyDenied):
                client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                )

    def test_deny_at_post_response(self):
        _auto(only="openai")
        allow = Verdict.allow()
        deny = Verdict.deny(reasoning="output bad")

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=allow,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=deny,
            ),
        ):
            from openai import OpenAI

            client = OpenAI()
            with pytest.raises(PolicyDenied):
                client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                )

    def test_modify_rewrites_output(self):
        _auto(only="openai")
        allow = Verdict.allow()
        modify = Verdict.modify(
            target="output",
            operation="replace",
            value="[REDACTED]",
        )

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=allow,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=modify,
            ),
        ):
            from openai import OpenAI

            client = OpenAI()
            resp = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
            )
            assert (
                resp.choices[0].message.content
                == "[REDACTED]"
            )

    def test_escalate_raises(self):
        _auto(only="openai")
        escalate = Verdict.escalate(
            type="human_confirm", prompt="review"
        )

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=escalate,
        ):
            from openai import OpenAI

            client = OpenAI()
            with pytest.raises(PolicyEscalation):
                client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                )

    # -- async ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_async_allow(self):
        _auto(only="openai")
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        resp = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert (
            resp.choices[0].message.content
            == OPENAI_RESPONSE_CONTENT
        )

    @pytest.mark.asyncio
    async def test_async_deny(self):
        _auto(only="openai")
        deny = Verdict.deny(reasoning="nope")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request",
            return_value=deny,
        ):
            from openai import AsyncOpenAI

            client = AsyncOpenAI()
            with pytest.raises(PolicyDenied):
                await client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                )


# ============================================================================
# Anthropic
# ============================================================================


class TestAnthropicInstrumentation:
    """Verify Anthropic ``Messages.create`` / ``AsyncMessages.create``."""

    def _get_classes(self):
        from anthropic.resources import (
            AsyncMessages,
            Messages,
        )

        return Messages, AsyncMessages

    def test_instrument_patches_create(self):
        Msgs, AMsgs = self._get_classes()
        orig = Msgs.create

        _auto(only="anthropic")

        assert "anthropic" in _instrumented
        assert Msgs.create is not orig

    def test_uninstrument_restores(self):
        Msgs, _ = self._get_classes()
        orig = Msgs.create

        _auto(only="anthropic")
        apl.uninstrument()

        assert Msgs.create is orig

    def test_allow_passes_through(self):
        _auto(only="anthropic")
        from anthropic import Anthropic

        client = Anthropic()
        resp = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
        )
        assert (
            resp.content[0].text
            == ANTHROPIC_RESPONSE_CONTENT
        )

    def test_deny_blocks(self):
        _auto(only="anthropic")
        deny = Verdict.deny(reasoning="blocked")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=deny,
        ):
            from anthropic import Anthropic

            client = Anthropic()
            with pytest.raises(PolicyDenied):
                client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                    max_tokens=100,
                )

    def test_modify_rewrites_output(self):
        _auto(only="anthropic")
        allow = Verdict.allow()
        modify = Verdict.modify(
            target="output",
            operation="replace",
            value="[SAFE]",
        )

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=allow,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=modify,
            ),
        ):
            from anthropic import Anthropic

            client = Anthropic()
            resp = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
                max_tokens=100,
            )
            assert resp.content[0].text == "[SAFE]"

    def test_escalate_raises(self):
        _auto(only="anthropic")
        esc = Verdict.escalate(
            type="human_confirm", prompt="review"
        )

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=esc,
        ):
            from anthropic import Anthropic

            client = Anthropic()
            with pytest.raises(PolicyEscalation):
                client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                    max_tokens=100,
                )

    @pytest.mark.asyncio
    async def test_async_allow(self):
        _auto(only="anthropic")
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
        resp = await client.messages.create(
            model="claude-sonnet-4-5-20250929",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
        )
        assert (
            resp.content[0].text
            == ANTHROPIC_RESPONSE_CONTENT
        )

    @pytest.mark.asyncio
    async def test_async_deny(self):
        _auto(only="anthropic")
        deny = Verdict.deny(reasoning="nope")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request",
            return_value=deny,
        ):
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic()
            with pytest.raises(PolicyDenied):
                await client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                    max_tokens=100,
                )


# ============================================================================
# LiteLLM
# ============================================================================


class TestLiteLLMInstrumentation:
    """Verify ``litellm.completion`` / ``litellm.acompletion``."""

    def test_instrument_patches(self):
        import litellm

        orig = litellm.completion

        _auto(only="litellm")

        assert "litellm" in _instrumented
        assert litellm.completion is not orig

    def test_uninstrument_restores(self):
        import litellm

        orig = litellm.completion

        _auto(only="litellm")
        apl.uninstrument()

        assert litellm.completion is orig

    def test_allow_passes_through(self):
        _auto(only="litellm")
        import litellm

        resp = litellm.completion(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert (
            resp.choices[0].message.content
            == LITELLM_RESPONSE_CONTENT
        )

    def test_deny_blocks(self):
        _auto(only="litellm")
        deny = Verdict.deny(reasoning="blocked")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=deny,
        ):
            import litellm

            with pytest.raises(PolicyDenied):
                litellm.completion(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                )

    def test_modify_rewrites_output(self):
        _auto(only="litellm")
        allow = Verdict.allow()
        modify = Verdict.modify(
            target="output",
            operation="replace",
            value="[CLEAN]",
        )

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=allow,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=modify,
            ),
        ):
            import litellm

            resp = litellm.completion(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
            )
            assert (
                resp.choices[0].message.content == "[CLEAN]"
            )

    def test_escalate_raises(self):
        _auto(only="litellm")
        esc = Verdict.escalate(
            type="human_confirm", prompt="confirm"
        )

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=esc,
        ):
            import litellm

            with pytest.raises(PolicyEscalation):
                litellm.completion(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                )

    @pytest.mark.asyncio
    async def test_async_allow(self):
        _auto(only="litellm")
        import litellm

        resp = await litellm.acompletion(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert (
            resp.choices[0].message.content
            == LITELLM_RESPONSE_CONTENT
        )

    @pytest.mark.asyncio
    async def test_async_deny(self):
        _auto(only="litellm")
        deny = Verdict.deny(reasoning="nope")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request",
            return_value=deny,
        ):
            import litellm

            with pytest.raises(PolicyDenied):
                await litellm.acompletion(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "user", "content": "hi"}
                    ],
                )


# ============================================================================
# LangChain
# ============================================================================


class TestLangChainInstrumentation:
    """Verify ``BaseChatModel.invoke`` / ``ainvoke``."""

    def _get_class(self):
        from langchain_core.language_models.chat_models import (
            BaseChatModel,
        )

        return BaseChatModel

    def test_instrument_patches(self):
        BCM = self._get_class()
        orig = BCM.invoke

        _auto(only="langchain")

        assert "langchain" in _instrumented
        assert BCM.invoke is not orig

    def test_uninstrument_restores(self):
        BCM = self._get_class()
        orig = BCM.invoke

        _auto(only="langchain")
        apl.uninstrument()

        assert BCM.invoke is orig

    def test_allow_passes_through(self):
        _auto(only="langchain")
        BCM = self._get_class()

        model = BCM()
        resp = model.invoke("Hello")
        assert resp.content == LANGCHAIN_RESPONSE_CONTENT

    def test_deny_blocks(self):
        _auto(only="langchain")
        deny = Verdict.deny(reasoning="blocked")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=deny,
        ):
            BCM = self._get_class()
            model = BCM()
            with pytest.raises(PolicyDenied):
                model.invoke("Hello")

    def test_modify_rewrites_output(self):
        _auto(only="langchain")
        allow = Verdict.allow()
        modify = Verdict.modify(
            target="output",
            operation="replace",
            value="[FILTERED]",
        )

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=allow,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=modify,
            ),
        ):
            BCM = self._get_class()
            model = BCM()
            resp = model.invoke("Hello")
            assert resp.content == "[FILTERED]"

    def test_escalate_raises(self):
        _auto(only="langchain")
        esc = Verdict.escalate(
            type="human_confirm", prompt="review"
        )

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=esc,
        ):
            BCM = self._get_class()
            model = BCM()
            with pytest.raises(PolicyEscalation):
                model.invoke("Hello")

    @pytest.mark.asyncio
    async def test_async_allow(self):
        _auto(only="langchain")
        BCM = self._get_class()
        model = BCM()
        resp = await model.ainvoke("Hello")
        assert resp.content == LANGCHAIN_RESPONSE_CONTENT

    @pytest.mark.asyncio
    async def test_async_deny(self):
        _auto(only="langchain")
        deny = Verdict.deny(reasoning="nope")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request",
            return_value=deny,
        ):
            BCM = self._get_class()
            model = BCM()
            with pytest.raises(PolicyDenied):
                await model.ainvoke("Hello")


# ============================================================================
# WatsonX
# ============================================================================


class TestWatsonXInstrumentation:
    """Verify ``ModelInference.chat``."""

    def _get_class(self):
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        return ModelInference

    def test_instrument_patches(self):
        MI = self._get_class()
        orig = MI.chat

        _auto(only="watsonx")

        assert "watsonx" in _instrumented
        assert MI.chat is not orig

    def test_uninstrument_restores(self):
        MI = self._get_class()
        orig = MI.chat

        _auto(only="watsonx")
        apl.uninstrument()

        assert MI.chat is orig

    def test_allow_passes_through(self):
        _auto(only="watsonx")
        MI = self._get_class()

        model = MI(model_id="ibm/granite-chat")
        resp = model.chat(
            messages=[{"role": "user", "content": "hi"}]
        )
        assert (
            resp["choices"][0]["message"]["content"]
            == WATSONX_RESPONSE_CONTENT
        )

    def test_deny_blocks(self):
        _auto(only="watsonx")
        deny = Verdict.deny(reasoning="blocked")

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=deny,
        ):
            MI = self._get_class()
            model = MI(model_id="ibm/granite-chat")
            with pytest.raises(PolicyDenied):
                model.chat(
                    messages=[
                        {"role": "user", "content": "hi"}
                    ]
                )

    def test_modify_rewrites_output(self):
        _auto(only="watsonx")
        allow = Verdict.allow()
        modify = Verdict.modify(
            target="output",
            operation="replace",
            value="[SCRUBBED]",
        )

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=allow,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=modify,
            ),
        ):
            MI = self._get_class()
            model = MI(model_id="ibm/granite-chat")
            resp = model.chat(
                messages=[{"role": "user", "content": "hi"}]
            )
            assert (
                resp["choices"][0]["message"]["content"]
                == "[SCRUBBED]"
            )

    def test_escalate_raises(self):
        _auto(only="watsonx")
        esc = Verdict.escalate(
            type="human_confirm", prompt="review"
        )

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=esc,
        ):
            MI = self._get_class()
            model = MI(model_id="ibm/granite-chat")
            with pytest.raises(PolicyEscalation):
                model.chat(
                    messages=[
                        {"role": "user", "content": "hi"}
                    ]
                )


# ============================================================================
# Cross-cutting: re-entrancy, fail-open, auto_instrument all at once
# ============================================================================


class TestCrossCutting:
    """Tests that span all providers or exercise shared infrastructure."""

    def test_auto_instrument_all_providers(self):
        """``auto_instrument()`` with defaults patches every installed lib."""
        apl.auto_instrument(policy_servers=[])

        assert "openai" in _instrumented
        assert "anthropic" in _instrumented
        assert "litellm" in _instrumented
        assert "langchain" in _instrumented
        assert "watsonx" in _instrumented

    def test_uninstrument_clears_all(self):
        apl.auto_instrument(policy_servers=[])
        apl.uninstrument()

        assert len(_instrumented) == 0

    def test_reentrancy_skips_policy(self):
        """Nested LLM calls inside a policy evaluation bypass the guard."""
        _auto(only="openai")

        inst._set_reentrant(True)
        try:
            from openai import OpenAI

            client = OpenAI()
            # Should NOT call any policy evaluation
            resp = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
            )
            assert (
                resp.choices[0].message.content
                == OPENAI_RESPONSE_CONTENT
            )
        finally:
            inst._set_reentrant(False)

    def test_fail_open_on_evaluation_error(self):
        """If policy evaluation raises an unexpected error, the call proceeds."""
        _auto(only="openai")

        def boom(*a, **kw):
            raise RuntimeError("policy server crashed")

        with patch.object(
            inst, "_evaluate_pre_request", side_effect=boom
        ):
            from openai import OpenAI

            client = OpenAI()
            # Should still succeed (fail-open)
            resp = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "user", "content": "hi"}
                ],
            )
            assert (
                resp.choices[0].message.content
                == OPENAI_RESPONSE_CONTENT
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
