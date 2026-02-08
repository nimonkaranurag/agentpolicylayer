"""
APL Auto-Instrumentation

Automatically instruments popular LLM clients and agent frameworks.
No manual hooks required - just call `apl.auto_instrument()` and you're protected.

This works like OpenTelemetry's auto-instrumentation: we monkey-patch the underlying
client libraries to intercept calls at the right points.

Supported Libraries:
    - openai (sync + async)
    - anthropic (sync + async)
    - litellm
    - langchain (ChatModels)
    - ibm-watsonx-ai (ModelInference.chat)

Usage:
    import apl

    # One line to protect everything
    apl.auto_instrument(
        policy_servers=["stdio://./my_policy.py"],
    )

    # Now use your LLM clients normally - APL intercepts automatically
    from openai import OpenAI
    client = OpenAI()
    response = client.chat.completions.create(...)  # <- APL evaluates policies here

How It Works:
    1. We wrap the original methods (e.g., `client.chat.completions.create`)
    2. Before the call: evaluate `llm.pre_request` policies
    3. After the call: evaluate `llm.post_response` and `output.pre_send` policies
    4. If DENY: raise PolicyDenied
    5. If MODIFY: alter the output before returning
    6. If ESCALATE: raise PolicyEscalation for the app to handle
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import sys
import threading
import uuid
from typing import Any, Callable, Optional, TypeVar

from .layer import (
    PolicyDenied,
    PolicyEscalation,
    PolicyLayer,
)
from .logging import console, get_logger
from .types import (
    Decision,
    EventPayload,
    EventType,
    Message,
    SessionMetadata,
    Verdict,
)

logger = get_logger("instrument")

# Track what we've instrumented
_instrumented: set[str] = set()
_policy_layer: Optional[PolicyLayer] = None
_session_metadata: Optional[SessionMetadata] = None

# Guard against re-entrant instrumentation calls (e.g. a policy server
# that itself calls an LLM should not trigger another policy evaluation).
_reentrancy_guard: threading.local = threading.local()

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# ASYNC HELPER - robust event-loop handling for sync wrappers
# =============================================================================

# Persistent event loop for APL operations (preserves subprocess streams)
_apl_loop: Optional[asyncio.AbstractEventLoop] = None
_apl_lock = threading.Lock()


def _get_apl_loop() -> asyncio.AbstractEventLoop:
    """Get or create the persistent APL event loop running in a background thread."""
    global _apl_loop
    with _apl_lock:
        if _apl_loop is None or not _apl_loop.is_running():
            _apl_loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=_apl_loop.run_forever, daemon=True
            )
            thread.start()
    return _apl_loop


def _run_async(coro):
    """
    Run an async coroutine from synchronous code.

    Uses a persistent background event loop so that subprocess streams
    (stdio transport) remain attached to the same loop across calls.
    """
    loop = _get_apl_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(
        timeout=30
    )  # 30s timeout to avoid hanging forever


# =============================================================================
# CORE INSTRUMENTATION
# =============================================================================


def auto_instrument(
    policy_servers: list[str],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    instrument_openai: bool = True,
    instrument_anthropic: bool = True,
    instrument_litellm: bool = True,
    instrument_langchain: bool = True,
    instrument_watsonx: bool = True,
) -> PolicyLayer:
    """
    Automatically instrument LLM clients with APL policy evaluation.

    This is the main entry point for zero-config APL integration.
    Call this once at startup, and all supported LLM calls will be
    automatically protected by your policies.

    Args:
        policy_servers: List of policy server URIs to connect to
        session_id: Optional session ID for tracking
        user_id: Optional user ID for policies that need it
        metadata: Optional additional metadata
        instrument_openai: Whether to instrument OpenAI client
        instrument_anthropic: Whether to instrument Anthropic client
        instrument_litellm: Whether to instrument LiteLLM
        instrument_langchain: Whether to instrument LangChain
        instrument_watsonx: Whether to instrument IBM watsonx.ai

    Returns:
        The PolicyLayer instance (for advanced usage)

    Example:
        import apl

        apl.auto_instrument(
            policy_servers=[
                "stdio://./policies/pii_filter.py",
                "stdio://./policies/budget.py",
            ],
            user_id="user-123",
        )

        # Now all OpenAI/Anthropic/WatsonX calls are protected
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello"}]
        )
    """
    global _policy_layer, _session_metadata

    console.print()
    console.print(
        "[bold cyan]🛡️  APL Auto-Instrumentation[/bold cyan]"
    )
    console.print()

    # Create policy layer
    _policy_layer = PolicyLayer()
    for uri in policy_servers:
        _policy_layer.add_server(uri)
        console.print(
            f"  [green]✓[/green] Connected: [cyan]{uri}[/cyan]"
        )

    # Create session metadata
    _session_metadata = SessionMetadata(
        session_id=session_id or str(uuid.uuid4()),
        user_id=user_id,
        custom=metadata or {},
    )

    # Instrument libraries
    if instrument_openai:
        _instrument_openai()

    if instrument_anthropic:
        _instrument_anthropic()

    if instrument_litellm:
        _instrument_litellm()

    if instrument_langchain:
        _instrument_langchain()

    if instrument_watsonx:
        _instrument_watsonx()

    console.print()
    console.print(
        "[bold green]  ✓ Auto-instrumentation complete[/bold green]"
    )
    console.print(
        f"  [dim]Session: {_session_metadata.session_id[:8]}...[/dim]"
    )
    console.print()

    return _policy_layer


def uninstrument():
    """
    Remove APL instrumentation from all libraries.

    This restores the original methods. Useful for testing or
    when you need to temporarily disable policy checking.
    """
    global _instrumented, _policy_layer

    # Restore originals (stored as _apl_original_*)
    for module_name in list(_instrumented):
        _uninstrument_module(module_name)

    _instrumented.clear()
    _policy_layer = None

    console.print("[dim]APL instrumentation removed[/dim]")


# =============================================================================
# OPENAI INSTRUMENTATION
# =============================================================================


def _instrument_openai():
    """Instrument the OpenAI library."""
    if "openai" in _instrumented:
        return

    try:
        import openai
        from openai.resources.chat import (
            AsyncCompletions,
            Completions,
        )
    except ImportError:
        logger.debug(
            "OpenAI not installed, skipping instrumentation"
        )
        return

    # Store originals
    Completions._apl_original_create = Completions.create
    AsyncCompletions._apl_original_create = (
        AsyncCompletions.create
    )

    # Wrap sync create
    @functools.wraps(Completions.create)
    def wrapped_create(self, *args, **kwargs):
        return _sync_wrapper(
            Completions._apl_original_create,
            self,
            *args,
            **kwargs,
        )

    # Wrap async create
    @functools.wraps(AsyncCompletions.create)
    async def wrapped_async_create(self, *args, **kwargs):
        return await _async_wrapper(
            AsyncCompletions._apl_original_create,
            self,
            *args,
            **kwargs,
        )

    Completions.create = wrapped_create
    AsyncCompletions.create = wrapped_async_create

    _instrumented.add("openai")
    console.print(
        "  [green]✓[/green] Instrumented: [white]openai[/white]"
    )


def _instrument_anthropic():
    """Instrument the Anthropic library."""
    if "anthropic" in _instrumented:
        return

    try:
        import anthropic
        from anthropic.resources import (
            AsyncMessages,
            Messages,
        )
    except ImportError:
        logger.debug(
            "Anthropic not installed, skipping instrumentation"
        )
        return

    # Store originals
    Messages._apl_original_create = Messages.create
    AsyncMessages._apl_original_create = (
        AsyncMessages.create
    )

    # Wrap sync create
    @functools.wraps(Messages.create)
    def wrapped_create(self, *args, **kwargs):
        return _sync_wrapper_anthropic(
            Messages._apl_original_create,
            self,
            *args,
            **kwargs,
        )

    # Wrap async create
    @functools.wraps(AsyncMessages.create)
    async def wrapped_async_create(self, *args, **kwargs):
        return await _async_wrapper_anthropic(
            AsyncMessages._apl_original_create,
            self,
            *args,
            **kwargs,
        )

    Messages.create = wrapped_create
    AsyncMessages.create = wrapped_async_create

    _instrumented.add("anthropic")
    console.print(
        "  [green]✓[/green] Instrumented: [white]anthropic[/white]"
    )


def _instrument_litellm():
    """Instrument the LiteLLM library."""
    if "litellm" in _instrumented:
        return

    try:
        import litellm
    except ImportError:
        logger.debug(
            "LiteLLM not installed, skipping instrumentation"
        )
        return

    # Store original
    litellm._apl_original_completion = litellm.completion
    litellm._apl_original_acompletion = litellm.acompletion

    @functools.wraps(litellm.completion)
    def wrapped_completion(*args, **kwargs):
        return _sync_wrapper_litellm(
            litellm._apl_original_completion,
            *args,
            **kwargs,
        )

    @functools.wraps(litellm.acompletion)
    async def wrapped_acompletion(*args, **kwargs):
        return await _async_wrapper_litellm(
            litellm._apl_original_acompletion,
            *args,
            **kwargs,
        )

    litellm.completion = wrapped_completion
    litellm.acompletion = wrapped_acompletion

    _instrumented.add("litellm")
    console.print(
        "  [green]✓[/green] Instrumented: [white]litellm[/white]"
    )


def _instrument_langchain():
    """Instrument LangChain ChatModels."""
    if "langchain" in _instrumented:
        return

    try:
        from langchain_core.language_models.chat_models import (
            BaseChatModel,
        )
    except ImportError:
        logger.debug(
            "LangChain not installed, skipping instrumentation"
        )
        return

    # Store original
    BaseChatModel._apl_original_invoke = (
        BaseChatModel.invoke
    )
    BaseChatModel._apl_original_ainvoke = (
        BaseChatModel.ainvoke
    )

    @functools.wraps(BaseChatModel.invoke)
    def wrapped_invoke(self, input, config=None, **kwargs):
        return _sync_wrapper_langchain(
            BaseChatModel._apl_original_invoke,
            self,
            input,
            config,
            **kwargs,
        )

    @functools.wraps(BaseChatModel.ainvoke)
    async def wrapped_ainvoke(
        self, input, config=None, **kwargs
    ):
        return await _async_wrapper_langchain(
            BaseChatModel._apl_original_ainvoke,
            self,
            input,
            config,
            **kwargs,
        )

    BaseChatModel.invoke = wrapped_invoke
    BaseChatModel.ainvoke = wrapped_ainvoke

    _instrumented.add("langchain")
    console.print(
        "  [green]✓[/green] Instrumented: [white]langchain[/white]"
    )


# =============================================================================
# WATSONX INSTRUMENTATION
# =============================================================================


def _instrument_watsonx():
    """
    Instrument IBM watsonx.ai ModelInference.chat().

    Only the chat endpoint is instrumented (the generation endpoint
    is legacy and not supported).
    """
    if "watsonx" in _instrumented:
        return

    try:
        from ibm_watsonx_ai.foundation_models import (
            ModelInference,
        )
    except ImportError:
        logger.debug(
            "ibm-watsonx-ai not installed, skipping instrumentation"
        )
        return

    # Store original
    ModelInference._apl_original_chat = ModelInference.chat

    @functools.wraps(ModelInference.chat)
    def wrapped_chat(self, *args, **kwargs):
        return _sync_wrapper_watsonx(
            ModelInference._apl_original_chat,
            self,
            *args,
            **kwargs,
        )

    ModelInference.chat = wrapped_chat

    _instrumented.add("watsonx")
    console.print(
        "  [green]✓[/green] Instrumented: [white]ibm-watsonx-ai[/white] (chat)"
    )


# =============================================================================
# WRAPPER IMPLEMENTATIONS
# =============================================================================


def _sync_wrapper(original_fn, self, *args, **kwargs):
    """Synchronous wrapper for OpenAI-style completions."""
    if _is_reentrant():
        return original_fn(self, *args, **kwargs)

    messages = kwargs.get("messages", [])
    model = kwargs.get("model", "unknown")

    # Pre-request policy check
    verdict = _safe_evaluate_pre_request_sync(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    # Apply modifications to messages if needed
    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "llm_prompt":
            kwargs["messages"] = verdict.modification.value

    # Make the actual call
    response = original_fn(self, *args, **kwargs)

    # Post-response policy check
    output_text = _extract_openai_output(response)
    verdict = _safe_evaluate_post_response_sync(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    # Apply output modifications
    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.choices[0].message.content = (
                verdict.modification.value
            )

    return response


async def _async_wrapper(
    original_fn, self, *args, **kwargs
):
    """Async wrapper for OpenAI-style completions."""
    if _is_reentrant():
        return await original_fn(self, *args, **kwargs)

    messages = kwargs.get("messages", [])
    model = kwargs.get("model", "unknown")

    # Pre-request policy check
    verdict = await _safe_evaluate_pre_request(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    # Apply modifications
    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "llm_prompt":
            kwargs["messages"] = verdict.modification.value

    # Make the actual call
    response = await original_fn(self, *args, **kwargs)

    # Post-response policy check
    output_text = _extract_openai_output(response)
    verdict = await _safe_evaluate_post_response(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    # Apply output modifications
    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.choices[0].message.content = (
                verdict.modification.value
            )

    return response


def _sync_wrapper_anthropic(
    original_fn, self, *args, **kwargs
):
    """Synchronous wrapper for Anthropic messages."""
    if _is_reentrant():
        return original_fn(self, *args, **kwargs)

    messages = kwargs.get("messages", [])
    model = kwargs.get("model", "unknown")

    verdict = _safe_evaluate_pre_request_sync(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    response = original_fn(self, *args, **kwargs)

    output_text = _extract_anthropic_output(response)
    verdict = _safe_evaluate_post_response_sync(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.content[0].text = (
                verdict.modification.value
            )

    return response


async def _async_wrapper_anthropic(
    original_fn, self, *args, **kwargs
):
    """Async wrapper for Anthropic messages."""
    if _is_reentrant():
        return await original_fn(self, *args, **kwargs)

    messages = kwargs.get("messages", [])
    model = kwargs.get("model", "unknown")

    verdict = await _safe_evaluate_pre_request(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    response = await original_fn(self, *args, **kwargs)

    output_text = _extract_anthropic_output(response)
    verdict = await _safe_evaluate_post_response(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.content[0].text = (
                verdict.modification.value
            )

    return response


def _sync_wrapper_litellm(original_fn, *args, **kwargs):
    """Wrapper for LiteLLM completion."""
    if _is_reentrant():
        return original_fn(*args, **kwargs)

    messages = kwargs.get("messages", [])
    model = kwargs.get("model", "unknown")

    verdict = _safe_evaluate_pre_request_sync(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    response = original_fn(*args, **kwargs)

    output_text = _extract_openai_output(response)
    verdict = _safe_evaluate_post_response_sync(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.choices[0].message.content = (
                verdict.modification.value
            )

    return response


async def _async_wrapper_litellm(
    original_fn, *args, **kwargs
):
    """Async wrapper for LiteLLM acompletion."""
    if _is_reentrant():
        return await original_fn(*args, **kwargs)

    messages = kwargs.get("messages", [])
    model = kwargs.get("model", "unknown")

    verdict = await _safe_evaluate_pre_request(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    response = await original_fn(*args, **kwargs)

    output_text = _extract_openai_output(response)
    verdict = await _safe_evaluate_post_response(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.choices[0].message.content = (
                verdict.modification.value
            )

    return response


def _sync_wrapper_langchain(
    original_fn, self, input, config, **kwargs
):
    """Wrapper for LangChain ChatModel.invoke."""
    if _is_reentrant():
        return original_fn(self, input, config, **kwargs)

    # Extract messages from input
    messages = _langchain_input_to_messages(input)
    model = getattr(self, "model_name", "unknown")

    verdict = _safe_evaluate_pre_request_sync(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    response = original_fn(self, input, config, **kwargs)

    output_text = (
        response.content
        if hasattr(response, "content")
        else str(response)
    )
    verdict = _safe_evaluate_post_response_sync(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.content = verdict.modification.value

    return response


async def _async_wrapper_langchain(
    original_fn, self, input, config, **kwargs
):
    """Async wrapper for LangChain ChatModel.ainvoke."""
    if _is_reentrant():
        return await original_fn(
            self, input, config, **kwargs
        )

    messages = _langchain_input_to_messages(input)
    model = getattr(self, "model_name", "unknown")

    verdict = await _safe_evaluate_pre_request(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    response = await original_fn(
        self, input, config, **kwargs
    )

    output_text = (
        response.content
        if hasattr(response, "content")
        else str(response)
    )
    verdict = await _safe_evaluate_post_response(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            response.content = verdict.modification.value

    return response


def _sync_wrapper_watsonx(
    original_fn, self, *args, **kwargs
):
    """
    Synchronous wrapper for IBM watsonx.ai ModelInference.chat().

    The WatsonX chat endpoint returns a plain dict with an OpenAI-compatible
    structure::

        {
            "choices": [{"message": {"role": "assistant", "content": "..."}, ...}],
            "model_id": "...",
            ...
        }

    Messages are passed as a kwarg (``messages=[...]``), and the model id
    lives on the ``ModelInference`` instance rather than as a call argument.
    """
    if _is_reentrant():
        return original_fn(self, *args, **kwargs)

    messages = kwargs.get("messages") or (
        args[0] if args else []
    )
    model = getattr(self, "model_id", None) or "unknown"

    # Pre-request policy check
    verdict = _safe_evaluate_pre_request_sync(
        messages, model
    )
    _handle_verdict(verdict, "pre_request")

    # Apply modifications to messages if needed
    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "llm_prompt":
            if "messages" in kwargs:
                kwargs["messages"] = (
                    verdict.modification.value
                )
            elif args:
                args = (verdict.modification.value,) + args[
                    1:
                ]

    # Make the actual call
    response = original_fn(self, *args, **kwargs)

    # Post-response policy check
    output_text = _extract_watsonx_output(response)
    verdict = _safe_evaluate_post_response_sync(
        output_text, messages
    )
    _handle_verdict(verdict, "post_response")

    # Apply output modifications
    if (
        verdict.decision == Decision.MODIFY
        and verdict.modification
    ):
        if verdict.modification.target == "output":
            try:
                response["choices"][0]["message"][
                    "content"
                ] = verdict.modification.value
            except (KeyError, IndexError, TypeError):
                logger.warning(
                    "Failed to apply output modification to WatsonX response"
                )

    return response


# =============================================================================
# POLICY EVALUATION HELPERS
# =============================================================================


async def _evaluate_pre_request(
    messages: list, model: str
) -> Verdict:
    """Evaluate pre-request policies."""
    if not _policy_layer:
        return Verdict.allow()

    apl_messages = _convert_messages(messages)

    return await _policy_layer.evaluate(
        event_type=EventType.LLM_PRE_REQUEST,
        messages=apl_messages,
        payload=EventPayload(llm_model=model),
        metadata=_session_metadata,
    )


async def _evaluate_post_response(
    output_text: str, original_messages: list
) -> Verdict:
    """Evaluate post-response and output policies."""
    if not _policy_layer:
        return Verdict.allow()

    apl_messages = _convert_messages(original_messages)

    return await _policy_layer.evaluate(
        event_type=EventType.OUTPUT_PRE_SEND,
        messages=apl_messages,
        payload=EventPayload(output_text=output_text),
        metadata=_session_metadata,
    )


# -- Fail-open wrappers -----------------------------------------------------
# These catch unexpected errors during policy evaluation so that the
# underlying LLM call is never blocked by an infrastructure failure.


async def _safe_evaluate_pre_request(
    messages: list, model: str
) -> Verdict:
    """Evaluate pre-request policies with fail-open semantics."""
    _set_reentrant(True)
    try:
        return await _evaluate_pre_request(messages, model)
    except (PolicyDenied, PolicyEscalation):
        raise
    except Exception:
        logger.error(
            "Policy evaluation failed (pre_request), failing open",
            exc_info=True,
        )
        return Verdict.allow(
            reasoning="Policy evaluation error (fail-open)"
        )
    finally:
        _set_reentrant(False)


async def _safe_evaluate_post_response(
    output_text: str, original_messages: list
) -> Verdict:
    """Evaluate post-response policies with fail-open semantics."""
    _set_reentrant(True)
    try:
        return await _evaluate_post_response(
            output_text, original_messages
        )
    except (PolicyDenied, PolicyEscalation):
        raise
    except Exception:
        logger.error(
            "Policy evaluation failed (post_response), failing open",
            exc_info=True,
        )
        return Verdict.allow(
            reasoning="Policy evaluation error (fail-open)"
        )
    finally:
        _set_reentrant(False)


def _safe_evaluate_pre_request_sync(
    messages: list, model: str
) -> Verdict:
    """Synchronous version of _safe_evaluate_pre_request."""
    return _run_async(
        _safe_evaluate_pre_request(messages, model)
    )


def _safe_evaluate_post_response_sync(
    output_text: str, original_messages: list
) -> Verdict:
    """Synchronous version of _safe_evaluate_post_response."""
    return _run_async(
        _safe_evaluate_post_response(
            output_text, original_messages
        )
    )


def _handle_verdict(verdict: Verdict, stage: str):
    """Handle a verdict, raising exceptions if needed."""
    if verdict.decision == Decision.DENY:
        logger.warning(
            f"Policy denied at {stage}: {verdict.reasoning}"
        )
        raise PolicyDenied(verdict)

    if verdict.decision == Decision.ESCALATE:
        logger.info(
            f"Policy escalation at {stage}: {verdict.reasoning}"
        )
        raise PolicyEscalation(verdict)


# =============================================================================
# RE-ENTRANCY GUARD
# =============================================================================


def _is_reentrant() -> bool:
    """Check if we are inside a policy evaluation already."""
    return getattr(_reentrancy_guard, "active", False)


def _set_reentrant(value: bool):
    """Mark the current thread as inside/outside policy evaluation."""
    _reentrancy_guard.active = value


# =============================================================================
# UTILITIES
# =============================================================================


def _convert_messages(messages: list) -> list[Message]:
    """Convert various message formats to APL Messages."""
    result = []

    for msg in messages:
        if isinstance(msg, dict):
            result.append(
                Message(
                    role=msg.get("role", "user"),
                    content=msg.get("content"),
                )
            )
        elif isinstance(msg, Message):
            result.append(msg)
        elif hasattr(msg, "role") and hasattr(
            msg, "content"
        ):
            result.append(
                Message(role=msg.role, content=msg.content)
            )

    return result


def _extract_openai_output(response) -> str:
    """Extract text content from OpenAI response."""
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        return ""


def _extract_anthropic_output(response) -> str:
    """Extract text content from Anthropic response."""
    try:
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""
    except (AttributeError, IndexError):
        return ""


def _extract_watsonx_output(response) -> str:
    """
    Extract text content from a WatsonX chat response.

    The response is a plain dict::

        {"choices": [{"message": {"content": "..."}}]}
    """
    try:
        return (
            response["choices"][0]["message"]["content"]
            or ""
        )
    except (KeyError, IndexError, TypeError):
        return ""


def _langchain_input_to_messages(input) -> list:
    """Convert LangChain input to message list."""
    if isinstance(input, str):
        return [{"role": "user", "content": input}]
    elif isinstance(input, list):
        return [
            {
                "role": getattr(m, "type", "user"),
                "content": getattr(m, "content", str(m)),
            }
            for m in input
        ]
    return []


def _uninstrument_module(module_name: str):
    """Restore original methods for a module."""
    if module_name == "openai":
        try:
            from openai.resources.chat import (
                AsyncCompletions,
                Completions,
            )

            if hasattr(Completions, "_apl_original_create"):
                Completions.create = (
                    Completions._apl_original_create
                )
            if hasattr(
                AsyncCompletions, "_apl_original_create"
            ):
                AsyncCompletions.create = (
                    AsyncCompletions._apl_original_create
                )
        except ImportError:
            pass

    elif module_name == "anthropic":
        try:
            from anthropic.resources import (
                AsyncMessages,
                Messages,
            )

            if hasattr(Messages, "_apl_original_create"):
                Messages.create = (
                    Messages._apl_original_create
                )
            if hasattr(
                AsyncMessages, "_apl_original_create"
            ):
                AsyncMessages.create = (
                    AsyncMessages._apl_original_create
                )
        except ImportError:
            pass

    elif module_name == "litellm":
        try:
            import litellm

            if hasattr(litellm, "_apl_original_completion"):
                litellm.completion = (
                    litellm._apl_original_completion
                )
            if hasattr(
                litellm, "_apl_original_acompletion"
            ):
                litellm.acompletion = (
                    litellm._apl_original_acompletion
                )
        except ImportError:
            pass

    elif module_name == "langchain":
        try:
            from langchain_core.language_models.chat_models import (
                BaseChatModel,
            )

            if hasattr(
                BaseChatModel, "_apl_original_invoke"
            ):
                BaseChatModel.invoke = (
                    BaseChatModel._apl_original_invoke
                )
            if hasattr(
                BaseChatModel, "_apl_original_ainvoke"
            ):
                BaseChatModel.ainvoke = (
                    BaseChatModel._apl_original_ainvoke
                )
        except ImportError:
            pass

    elif module_name == "watsonx":
        try:
            from ibm_watsonx_ai.foundation_models import (
                ModelInference,
            )

            if hasattr(
                ModelInference, "_apl_original_chat"
            ):
                ModelInference.chat = (
                    ModelInference._apl_original_chat
                )
        except ImportError:
            pass
