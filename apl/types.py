"""
APL (Agent Policy Layer) - Core Protocol Types

Design Philosophy:
- Use chat/completions format as the conversation context (de facto standard)
- Wrap it in an event envelope with lifecycle + metadata context
- Policies declare what context they need (context contracts)
- Verdicts are rich: allow/deny/modify/escalate/observe

The protocol types are pydantic models so that (a) validation happens on
deserialize for free, (b) the domain types enforce their own invariants
(see :class:`Verdict`), and (c) the wire codec in ``apl.serialization`` is a
thin shim over ``model_dump``/``model_validate`` rather than hand-written
per-field serializers.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("apl")

# The protocol/wire version this build speaks. Single-sourced here and reused as
# the manifest default below and by the client's compatibility check on connect.
# (WP-8 owns folding the remaining "0.3.0" literals — pyproject, the CLI info
# command, the CLI banner — onto this constant.)
PROTOCOL_VERSION = "0.3.0"


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# FAILURE HANDLING - what to do when a policy cannot be evaluated
# =============================================================================


class PolicyUnavailableError(Exception):
    """
    Raised when a policy cannot be evaluated, so no verdict can be obtained.

    Transports raise this on connection failure, timeout, or a non-success response.
    Callers translate it into the configured :class:`FailMode` instead of silently
    treating the failure as an allow.
    """


class FailMode(str, Enum):
    """
    What to do when a policy is unavailable.

    A policy is "unavailable" when it times out, raises, returns something that
    is not a :class:`Verdict`, or its server cannot be reached. Because APL is a
    guardrails layer, the default must be safe:

    - ``CLOSED`` (default): an unavailable policy DENIES the action.
    - ``OPEN``: an unavailable policy ALLOWS the action. This disables
      enforcement on failure and must be opted into explicitly.
    """

    CLOSED = "closed"
    OPEN = "open"


# =============================================================================
# EVENT TYPES - Standardized moments in the agent lifecycle
# =============================================================================


class EventType(str, Enum):
    """
    Lifecycle events that policies can subscribe to.

    These are the "hooks" into the agent loop. A policy declares which events it cares
    about, and only receives those.
    """

    # Input processing
    INPUT_RECEIVED = "input.received"  # User message received
    INPUT_VALIDATED = "input.validated"  # After input validation

    # Planning/reasoning
    PLAN_PROPOSED = "plan.proposed"  # Agent proposed a plan
    PLAN_APPROVED = "plan.approved"  # Plan approved for execution

    # LLM interactions
    LLM_PRE_REQUEST = "llm.pre_request"  # Before calling LLM
    LLM_POST_RESPONSE = "llm.post_response"  # After LLM responds

    # Tool execution
    TOOL_PRE_INVOKE = "tool.pre_invoke"  # Before tool execution
    TOOL_POST_INVOKE = "tool.post_invoke"  # After tool execution

    # Multi-agent
    AGENT_PRE_HANDOFF = "agent.pre_handoff"  # Before handing off to another agent
    AGENT_POST_HANDOFF = "agent.post_handoff"  # After receiving from another agent

    # Output
    OUTPUT_PRE_SEND = "output.pre_send"  # Before sending response to user

    # Session lifecycle
    SESSION_START = "session.start"
    SESSION_END = "session.end"


# =============================================================================
# CONTEXT - What policies receive (chat/completions + metadata)
# =============================================================================
#
# Defined leaf-first (FunctionCall -> ToolCall -> Message) so the nested model
# references resolve without forward-ref rebuilding under
# ``from __future__ import annotations``.


class FunctionCall(BaseModel):
    """Function call details."""

    name: str
    arguments: str  # JSON string, as per OpenAI spec


class ToolCall(BaseModel):
    """Tool call within an assistant message."""

    id: str
    type: Literal["function"] = "function"
    # A tool call without its function is meaningless and used to AttributeError
    # during serialization; make it required so that illegal state can't exist.
    function: FunctionCall


class Message(BaseModel):
    """
    OpenAI chat/completions compatible message format.

    ``role`` is a free ``str`` (conventionally ``system``/``user``/``assistant``/
    ``tool``) rather than a strict literal: messages are adapted in-process from
    arbitrary provider SDKs whose role vocabularies drift (``function``, ``developer``,
    ...), and rejecting an unrecognised role would crash instrumentation or spuriously
    deny a legitimate turn.
    """

    role: str
    content: Optional[str] = None
    name: Optional[str] = None  # For tool messages
    tool_calls: Optional[list[ToolCall]] = None  # For assistant messages
    tool_call_id: Optional[str] = None  # For tool messages


class SessionMetadata(BaseModel):
    """Session-level context that isn't in the conversation."""

    session_id: str = Field(default_factory=_new_uuid)
    user_id: Optional[str] = None
    agent_id: Optional[str] = None

    # Token tracking
    token_count: int = 0
    token_budget: Optional[int] = None

    # Cost tracking
    cost_usd: float = 0.0
    cost_budget_usd: Optional[float] = None

    # Permissions & compliance
    user_roles: list[str] = Field(default_factory=list)
    user_region: Optional[str] = None  # For GDPR, data residency
    compliance_tags: list[str] = Field(default_factory=list)

    # Timing (timezone-aware; round-trips through the wire codec)
    started_at: datetime = Field(default_factory=_now_utc)

    # Extensible
    custom: dict[str, Any] = Field(default_factory=dict)


class EventPayload(BaseModel):
    """
    Event-specific payload - the "delta" or what's happening NOW.

    Different events populate different fields.
    """

    # For tool events
    tool_name: Optional[str] = None
    tool_args: Optional[dict[str, Any]] = None
    tool_result: Optional[Any] = None
    tool_error: Optional[str] = None

    # For LLM events
    llm_model: Optional[str] = None
    llm_prompt: Optional[list[Message]] = None
    llm_response: Optional[Message] = None
    llm_tokens_used: Optional[int] = None

    # For output events
    output_text: Optional[str] = None
    output_structured: Optional[dict[str, Any]] = None

    # For planning events
    plan: Optional[list[str]] = None

    # For multi-agent events
    target_agent: Optional[str] = None
    source_agent: Optional[str] = None
    handoff_payload: Optional[dict[str, Any]] = None


class PolicyEvent(BaseModel):
    """
    The complete event sent to policy servers.

    Structure:
    - Envelope: id, type, timestamp (when/what)
    - Messages: chat/completions format (conversation history)
    - Payload: event-specific data (the delta)
    - Metadata: session context (who/where/limits)

    The envelope fields carry defaults so a sparse inbound event decodes
    leniently (matching the prior serializer); tightening inbound validation
    on the server transport is WP-7's concern (§3.11).
    """

    id: str = Field(default_factory=_new_uuid)
    type: EventType = EventType.INPUT_RECEIVED
    timestamp: datetime = Field(default_factory=_now_utc)

    # Conversation context - chat/completions format
    messages: list[Message] = Field(default_factory=list)

    # Event-specific payload
    payload: EventPayload = Field(default_factory=EventPayload)

    # Session metadata
    metadata: SessionMetadata = Field(default_factory=SessionMetadata)


# =============================================================================
# VERDICTS - What policies return
# =============================================================================


class Decision(str, Enum):
    """
    Policy decisions.

    Not just allow/deny!
        - ALLOW: Proceed as planned
        - DENY: Block the action
        - MODIFY: Proceed with modifications
        - ESCALATE: Requires human intervention
        - OBSERVE: Non-blocking, just record
    """

    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"
    ESCALATE = "escalate"
    OBSERVE = "observe"


class Modification(BaseModel):
    """How to modify the action/content."""

    # Every target the enforcement engine can apply: the instrumentation event
    # table (apl/instrumentation/events) wires accessors for all of these, so a
    # narrower set would silently make a built-in capability unconstructable
    # (e.g. a redact on ``plan``). Keep in sync with that table.
    target: Literal[
        "input",
        "tool_args",
        "llm_prompt",
        "output",
        "tool_result",
        "plan",
        "handoff_payload",
    ]
    operation: Literal[
        "replace",
        "redact",
        "append",
        "prepend",
        "patch",
    ]
    value: Any

    # For patch operations
    path: Optional[str] = None  # JSON path for surgical modifications


class Escalation(BaseModel):
    """How to escalate to humans."""

    type: Literal[
        "human_confirm",
        "human_review",
        "abort",
        "fallback",
    ]
    prompt: Optional[str] = None  # What to show the human
    fallback_action: Optional[str] = None  # What to do instead
    timeout_ms: Optional[int] = None  # How long to wait

    # For structured confirmations
    options: Optional[list[str]] = None  # e.g., ["Proceed", "Cancel", "Modify"]


class Verdict(BaseModel):
    """
    Policy response.

    Invariants (enforced on construction *and* deserialize):
    - ``confidence`` is in ``[0, 1]`` — weighted composition sums it, so an
      out-of-range value can't be allowed to skew the vote.
    - a ``MODIFY`` verdict carries at least one modification.
    - an ``ESCALATE`` verdict carries an escalation.
    """

    decision: Decision
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: Optional[str] = None
    modifications: list[Modification] = Field(default_factory=list)
    escalation: Optional[Escalation] = None
    policy_name: Optional[str] = None
    policy_version: Optional[str] = None
    evaluation_ms: Optional[float] = None
    trace: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def _check_decision_invariants(self) -> Verdict:
        if self.decision is Decision.MODIFY and not self.modifications:
            raise ValueError("a MODIFY verdict must carry at least one modification")
        if self.decision is Decision.ESCALATE and self.escalation is None:
            raise ValueError("an ESCALATE verdict must carry an escalation")
        return self

    @classmethod
    def allow(
        cls,
        reasoning: str = None,
        confidence: float = 1.0,
    ) -> Verdict:
        return cls(
            decision=Decision.ALLOW,
            reasoning=reasoning,
            confidence=confidence,
        )

    @classmethod
    def deny(cls, reasoning: str, confidence: float = 1.0) -> Verdict:
        return cls(
            decision=Decision.DENY,
            reasoning=reasoning,
            confidence=confidence,
        )

    @classmethod
    def modify(
        cls,
        target: str,
        operation: str,
        value: Any,
        reasoning: str = None,
        confidence: float = 1.0,
        path: str = None,
    ) -> Verdict:
        return cls(
            decision=Decision.MODIFY,
            reasoning=reasoning,
            confidence=confidence,
            modifications=[
                Modification(
                    target=target,
                    operation=operation,
                    value=value,
                    path=path,
                )
            ],
        )

    @classmethod
    def escalate(
        cls,
        type: str,
        prompt: str = None,
        reasoning: str = None,
        timeout_ms: int = None,
        fallback_action: str = None,
        options: list[str] = None,
    ) -> Verdict:
        return cls(
            decision=Decision.ESCALATE,
            reasoning=reasoning,
            escalation=Escalation(
                type=type,
                prompt=prompt,
                timeout_ms=timeout_ms,
                fallback_action=fallback_action,
                options=options,
            ),
        )

    @classmethod
    def observe(cls, reasoning: str = None, trace: dict = None) -> Verdict:
        return cls(
            decision=Decision.OBSERVE,
            reasoning=reasoning,
            trace=trace,
        )

    @classmethod
    def unavailable(
        cls,
        fail_mode: FailMode,
        reasoning: str,
        *,
        policy_name: Optional[str] = None,
        evaluation_ms: Optional[float] = None,
    ) -> Verdict:
        """
        Build the verdict to use when a policy could not be evaluated.

        For a guardrails product the safe default is to treat an unavailable policy as a
        denial (``FailMode.CLOSED``); ``FailMode.OPEN`` — which must be opted into
        explicitly — downgrades it to an allow. Either way the reasoning records that
        this was an availability failure rather than a deliberate policy decision.
        """
        decision = Decision.ALLOW if fail_mode is FailMode.OPEN else Decision.DENY
        return cls(
            decision=decision,
            confidence=1.0,
            reasoning=reasoning,
            policy_name=policy_name,
            evaluation_ms=evaluation_ms,
        )


# =============================================================================
# CONTEXT CONTRACTS - What policies declare they need
# =============================================================================


class ContextRequirement(BaseModel):
    """
    A single context field requirement.

    Policies declare what they need, runtimes provide it.
    This enables portability - policies don't parse full agent state.
    """

    path: str  # e.g., "metadata.user_region"
    required: bool = True  # If False, policy handles missing
    description: Optional[str] = None  # For documentation


class PolicyDefinition(BaseModel):
    """
    How a policy server describes its policies to the runtime.

    This is sent during registration/handshake.
    """

    name: str
    version: str

    # What events this policy handles
    events: list[EventType]

    # What context it needs (the contract)
    context_requirements: list[ContextRequirement] = Field(default_factory=list)

    # Execution characteristics
    blocking: bool = True  # Must await vs fire-and-forget
    timeout_ms: int = 1000  # Max evaluation time

    # Metadata
    description: Optional[str] = None
    author: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class PolicyManifest(BaseModel):
    """
    Complete manifest from a policy server.

    Sent during initialization handshake.
    """

    server_name: str
    server_version: str
    protocol_version: str = PROTOCOL_VERSION

    policies: list[PolicyDefinition] = Field(default_factory=list)

    # Server capabilities
    supports_batch: bool = False  # Can handle multiple events at once
    supports_streaming: bool = False  # Can stream verdicts

    # Documentation
    description: Optional[str] = None
    documentation_url: Optional[str] = None


# =============================================================================
# COMPOSITION - How multiple policies combine
# =============================================================================


class CompositionMode(str, Enum):
    """How to combine verdicts from multiple policies."""

    DENY_OVERRIDES = "deny_overrides"  # Any deny wins
    ALLOW_OVERRIDES = "allow_overrides"  # Any allow wins (rare)
    UNANIMOUS = "unanimous"  # All must agree
    FIRST_APPLICABLE = "first_applicable"  # First non-observe wins
    WEIGHTED = "weighted"  # Confidence-weighted voting


class CompositionConfig(BaseModel):
    """Configuration for verdict composition."""

    mode: CompositionMode = CompositionMode.DENY_OVERRIDES

    # Execution settings
    parallel: bool = True  # Evaluate policies in parallel
    timeout_ms: int = 500  # Total timeout for all policies

    # What happens when a policy is unavailable (error/timeout/unreachable).
    # CLOSED (default) denies; OPEN allows. This is the single source of truth
    # for fail behaviour and is consumed by the client and instrumentation paths.
    fail_mode: FailMode = FailMode.CLOSED

    # Decision applied when the layer-level timeout fires. Defaults to deny so
    # the default is fail-closed; the layer timeout itself is wired in WP-2.
    on_timeout: Decision = Decision.DENY

    # Priority ordering (policy names, first = highest priority)
    priority: list[str] = Field(default_factory=list)

    # For weighted mode
    weights: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _warn_when_fail_open(self) -> CompositionConfig:
        if self.fail_mode is FailMode.OPEN:
            logger.warning(
                "APL is configured FAIL-OPEN: policy errors, timeouts, and "
                "unreachable servers will ALLOW the action instead of denying "
                "it. Enforcement is disabled whenever a policy is unavailable."
            )
        return self
