"""
APL WatsonX Instrumentation Tests

Tests that APL policies are correctly applied when using IBM watsonx.ai
ModelInference.chat() — the only supported endpoint (generation is legacy).

These tests mock the watsonx SDK so they run without IBM credentials.
"""

import asyncio
import os
import sys
import types
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

from apl import (
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    PolicyServer,
    SessionMetadata,
    Verdict,
)
from apl.instrument import (
    _convert_messages,
    _extract_watsonx_output,
    _instrumented,
    _sync_wrapper_watsonx,
)
from apl.layer import PolicyDenied, PolicyEscalation

# =============================================================================
# Fake watsonx SDK — enough surface area for instrumentation tests
# =============================================================================


def _build_fake_watsonx_module():
    """
    Create a minimal fake ``ibm_watsonx_ai`` package so that
    ``_instrument_watsonx`` can import from it without the real SDK.
    """
    # ibm_watsonx_ai
    ibm_watsonx_ai = types.ModuleType("ibm_watsonx_ai")

    # ibm_watsonx_ai.foundation_models
    foundation_models = types.ModuleType(
        "ibm_watsonx_ai.foundation_models"
    )

    class ModelInference:
        """Minimal stand-in for the real ModelInference."""

        def __init__(self, model_id="test-model", **kw):
            self.model_id = model_id

        def chat(self, messages=None, **kwargs):
            """Return an OpenAI-compatible dict response."""
            return {
                "id": f"chat-{uuid.uuid4().hex[:8]}",
                "model_id": self.model_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from WatsonX!",
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


@pytest.fixture(autouse=True)
def _install_fake_watsonx(monkeypatch):
    """
    Install the fake watsonx modules into ``sys.modules`` for every test,
    then clean up afterwards.
    """
    fake_modules = _build_fake_watsonx_module()
    for name, mod in fake_modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    yield


@pytest.fixture(autouse=True)
def _clean_instrumentation():
    """Ensure instrumentation state is clean between tests."""
    yield
    # Reset module-level state after each test
    import apl.instrument as inst

    inst._instrumented.clear()
    inst._policy_layer = None
    inst._session_metadata = None


# =============================================================================
# _extract_watsonx_output
# =============================================================================


class TestExtractWatsonxOutput:
    def test_normal_response(self):
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hi there",
                    }
                }
            ]
        }
        assert (
            _extract_watsonx_output(response) == "Hi there"
        )

    def test_empty_content(self):
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                    }
                }
            ]
        }
        assert _extract_watsonx_output(response) == ""

    def test_none_content(self):
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                    }
                }
            ]
        }
        assert _extract_watsonx_output(response) == ""

    def test_missing_choices(self):
        assert _extract_watsonx_output({}) == ""

    def test_empty_choices(self):
        assert (
            _extract_watsonx_output({"choices": []}) == ""
        )

    def test_malformed_response(self):
        assert _extract_watsonx_output(None) == ""
        assert _extract_watsonx_output("not a dict") == ""


# =============================================================================
# _instrument_watsonx / uninstrument round-trip
# =============================================================================


class TestWatsonxInstrumentation:
    def test_instrument_patches_chat(self):
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        original_chat = ModelInference.chat

        from apl.instrument import _instrument_watsonx

        _instrument_watsonx()

        assert "watsonx" in _instrumented
        # The method should now be wrapped
        assert ModelInference.chat is not original_chat
        # But the original is saved
        assert (
            ModelInference._apl_original_chat
            is original_chat
        )

    def test_instrument_idempotent(self):
        from apl.instrument import _instrument_watsonx

        _instrument_watsonx()
        _instrument_watsonx()  # second call should be a no-op
        assert _instrumented == {"watsonx"}

    def test_uninstrument_restores_chat(self):
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        original_chat = ModelInference.chat

        from apl.instrument import (
            _instrument_watsonx,
            _uninstrument_module,
        )

        _instrument_watsonx()
        assert ModelInference.chat is not original_chat

        _uninstrument_module("watsonx")
        assert ModelInference.chat is original_chat


# =============================================================================
# Policy enforcement through the WatsonX wrapper
# =============================================================================


class TestWatsonxPolicyEnforcement:
    """
    Verify that policies are evaluated for WatsonX chat calls and that
    DENY / MODIFY / ALLOW verdicts are handled correctly.
    """

    def _make_model(self):
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        return ModelInference(model_id="ibm/granite-chat")

    @staticmethod
    def _unbound_chat():
        """Return the unbound chat method from the class (not an instance)."""
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        return ModelInference.chat

    def test_chat_passthrough_without_policy_layer(self):
        """Without a policy layer, chat should work normally."""
        model = self._make_model()
        response = model.chat(
            messages=[{"role": "user", "content": "Hello"}]
        )
        assert response["choices"][0]["message"][
            "content"
        ] == ("Hello from WatsonX!")

    def test_policy_deny_blocks_pre_request(self):
        """A DENY verdict at pre_request should raise PolicyDenied."""
        import apl.instrument as inst

        deny_verdict = Verdict.deny(
            reasoning="Blocked by policy"
        )

        model = self._make_model()

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=deny_verdict,
        ):
            with pytest.raises(PolicyDenied) as exc_info:
                _sync_wrapper_watsonx(
                    self._unbound_chat(),
                    model,
                    messages=[
                        {
                            "role": "user",
                            "content": "Hello",
                        }
                    ],
                )
            assert "Blocked by policy" in str(
                exc_info.value
            )

    def test_policy_deny_blocks_post_response(self):
        """A DENY verdict at post_response should raise PolicyDenied."""
        import apl.instrument as inst

        allow = Verdict.allow()
        deny = Verdict.deny(
            reasoning="Output contains secrets"
        )

        model = self._make_model()

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
            with pytest.raises(PolicyDenied) as exc_info:
                _sync_wrapper_watsonx(
                    self._unbound_chat(),
                    model,
                    messages=[
                        {
                            "role": "user",
                            "content": "Hello",
                        }
                    ],
                )
            assert "Output contains secrets" in str(
                exc_info.value
            )

    def test_policy_modify_rewrites_output(self):
        """A MODIFY verdict should rewrite the response content."""
        import apl.instrument as inst

        allow = Verdict.allow()
        modify = Verdict.modify(
            target="output",
            operation="replace",
            value="[REDACTED]",
            reasoning="PII found",
        )

        model = self._make_model()

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
            response = _sync_wrapper_watsonx(
                self._unbound_chat(),
                model,
                messages=[
                    {"role": "user", "content": "Hello"}
                ],
            )

        assert (
            response["choices"][0]["message"]["content"]
            == "[REDACTED]"
        )

    def test_policy_modify_rewrites_messages(self):
        """A MODIFY verdict targeting llm_prompt should update messages."""
        import apl.instrument as inst

        new_messages = [
            {"role": "user", "content": "Sanitised input"}
        ]
        modify = Verdict.modify(
            target="llm_prompt",
            operation="replace",
            value=new_messages,
        )
        allow = Verdict.allow()

        model = self._make_model()
        call_log = []

        def spy_chat(self, *args, **kwargs):
            call_log.append(kwargs.get("messages", []))
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        }
                    }
                ]
            }

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=modify,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=allow,
            ),
        ):
            _sync_wrapper_watsonx(
                spy_chat,
                model,
                messages=[
                    {
                        "role": "user",
                        "content": "original",
                    }
                ],
            )

        assert call_log[0] == new_messages

    def test_policy_allow_passes_through(self):
        """An ALLOW verdict should return the original response unchanged."""
        import apl.instrument as inst

        allow = Verdict.allow()

        model = self._make_model()

        with (
            patch.object(
                inst,
                "_safe_evaluate_pre_request_sync",
                return_value=allow,
            ),
            patch.object(
                inst,
                "_safe_evaluate_post_response_sync",
                return_value=allow,
            ),
        ):
            response = _sync_wrapper_watsonx(
                self._unbound_chat(),
                model,
                messages=[
                    {"role": "user", "content": "Hello"}
                ],
            )

        assert (
            response["choices"][0]["message"]["content"]
            == "Hello from WatsonX!"
        )

    def test_policy_escalate_raises(self):
        """An ESCALATE verdict should raise PolicyEscalation."""
        import apl.instrument as inst

        escalate = Verdict.escalate(
            type="human_confirm",
            prompt="Please review",
        )

        model = self._make_model()

        with patch.object(
            inst,
            "_safe_evaluate_pre_request_sync",
            return_value=escalate,
        ):
            with pytest.raises(PolicyEscalation):
                _sync_wrapper_watsonx(
                    self._unbound_chat(),
                    model,
                    messages=[
                        {
                            "role": "user",
                            "content": "Hello",
                        }
                    ],
                )


# =============================================================================
# End-to-end: auto_instrument with WatsonX
# =============================================================================


class TestAutoInstrumentWatsonx:
    """
    Test that ``apl.auto_instrument()`` patches ModelInference.chat and
    that policies are applied through the full call path.
    """

    def test_auto_instrument_patches_watsonx(self):
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        original_chat = ModelInference.chat

        import apl

        # Only instrument watsonx to keep the test focused
        layer = apl.auto_instrument(
            policy_servers=[],
            instrument_openai=False,
            instrument_anthropic=False,
            instrument_litellm=False,
            instrument_langchain=False,
            instrument_watsonx=True,
        )

        assert "watsonx" in _instrumented
        assert ModelInference.chat is not original_chat

        # Clean up
        apl.uninstrument()
        assert ModelInference.chat is original_chat

    def test_chat_works_after_auto_instrument(self):
        import apl

        layer = apl.auto_instrument(
            policy_servers=[],
            instrument_openai=False,
            instrument_anthropic=False,
            instrument_litellm=False,
            instrument_langchain=False,
            instrument_watsonx=True,
        )

        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        model = ModelInference(model_id="ibm/granite-chat")
        response = model.chat(
            messages=[{"role": "user", "content": "Hello"}]
        )

        assert (
            response["choices"][0]["message"]["content"]
            == "Hello from WatsonX!"
        )

        apl.uninstrument()


# =============================================================================
# Reentrancy guard
# =============================================================================


class TestReentrancyGuard:
    """Verify that nested LLM calls skip policy evaluation."""

    def test_reentrant_call_skips_policy(self):
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )

        import apl.instrument as inst

        model = ModelInference(model_id="test")

        # Simulate being inside a policy evaluation
        inst._set_reentrant(True)
        try:
            # Should bypass policy checks entirely and return
            # the original response
            response = _sync_wrapper_watsonx(
                ModelInference.chat,
                model,
                messages=[
                    {"role": "user", "content": "Hello"}
                ],
            )
            assert (
                response["choices"][0]["message"]["content"]
                == "Hello from WatsonX!"
            )
        finally:
            inst._set_reentrant(False)


# =============================================================================
# Convert messages from WatsonX dict format
# =============================================================================


class TestConvertMessages:
    """Ensure WatsonX-style dict messages are converted to APL Messages."""

    def test_dict_messages(self):
        msgs = [
            {
                "role": "system",
                "content": "You are helpful.",
            },
            {"role": "user", "content": "Hi"},
        ]
        converted = _convert_messages(msgs)
        assert len(converted) == 2
        assert converted[0].role == "system"
        assert converted[0].content == "You are helpful."
        assert converted[1].role == "user"
        assert converted[1].content == "Hi"


# =============================================================================
# Policy server integration (in-process, no stdio)
# =============================================================================


class TestPolicyServerIntegration:
    """
    Verify that a real PolicyServer (evaluated in-process) correctly
    blocks or modifies WatsonX chat responses.
    """

    @pytest.mark.asyncio
    async def test_deny_policy_fires_for_watsonx_output(
        self,
    ):
        server = PolicyServer("watsonx-guard")

        @server.policy(
            name="block-secrets",
            events=["output.pre_send"],
            context=["payload.output_text"],
        )
        async def block_secrets(event):
            text = event.payload.output_text or ""
            if "SECRET" in text:
                return Verdict.deny(
                    reasoning="Output contains secret"
                )
            return Verdict.allow()

        # Simulate the event APL would create after a WatsonX chat call
        event = PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType.OUTPUT_PRE_SEND,
            timestamp=datetime.utcnow(),
            messages=[
                Message(
                    role="user", content="Tell me a secret"
                )
            ],
            payload=EventPayload(
                output_text="The SECRET code is 1234"
            ),
            metadata=SessionMetadata(session_id="test"),
        )

        verdicts = await server.evaluate(event)
        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.DENY
        assert "secret" in verdicts[0].reasoning.lower()

    @pytest.mark.asyncio
    async def test_modify_policy_redacts_watsonx_output(
        self,
    ):
        server = PolicyServer("watsonx-pii-filter")

        @server.policy(
            name="redact-email",
            events=["output.pre_send"],
            context=["payload.output_text"],
        )
        async def redact_email(event):
            import re

            text = event.payload.output_text or ""
            redacted = re.sub(
                r"[\w.+-]+@[\w-]+\.[\w.]+",
                "[EMAIL REDACTED]",
                text,
            )
            if redacted != text:
                return Verdict.modify(
                    target="output",
                    operation="replace",
                    value=redacted,
                    reasoning="Email address redacted",
                )
            return Verdict.allow()

        event = PolicyEvent(
            id=str(uuid.uuid4()),
            type=EventType.OUTPUT_PRE_SEND,
            timestamp=datetime.utcnow(),
            messages=[],
            payload=EventPayload(
                output_text="Contact john@example.com for details."
            ),
            metadata=SessionMetadata(session_id="test"),
        )

        verdicts = await server.evaluate(event)
        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.MODIFY
        assert (
            "[EMAIL REDACTED]"
            in verdicts[0].modification.value
        )
        assert (
            "john@example.com"
            not in verdicts[0].modification.value
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
