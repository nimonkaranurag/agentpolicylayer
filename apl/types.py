"""
APL (Agent Policy Layer) - Core Protocol Types

Design Philosophy:
- Use chat/completions format as the conversation context (de facto standard)
- Wrap it in an event envelope with lifecycle + metadata context
- Policies declare what context they need (context contracts)
- Verdicts are rich: allow/deny/modify/escalate/observe
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

# =============================================================================
# EVENT TYPES - Standardized moments in the agent lifecycle
# =============================================================================


class EventType(str, Enum):
    """
    Lifecycle events that policies can subscribe to.

    These are the "hooks" into the agent loop. A policy declares which
    events it cares about, and only receives those.
    """

    # Input processing
    INPUT_RECEIVED = (
        "input.received"  # User message received
    )
    INPUT_VALIDATED = (
        "input.validated"  # After input validation
    )

    # Planning/reasoning
    PLAN_PROPOSED = (
        "plan.proposed"  # Agent proposed a plan
    )
    PLAN_APPROVED = (
        "plan.approved"  # Plan approved for execution
    )

    # LLM interactions
    LLM_PRE_REQUEST = (
        "llm.pre_request"  # Before calling LLM
    )
    LLM_POST_RESPONSE = (
        "llm.post_response"  # After LLM responds
    )

    # Tool execution
    TOOL_PRE_INVOKE = (
        "tool.pre_invoke"  # Before tool execution
    )
    TOOL_POST_INVOKE = (
        "tool.post_invoke"  # After tool execution
    )

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


@dataclass
class Message:
    """
    OpenAI chat/completions compatible message format.
    """

    role: Literal[
        "system", "user", "assistant", "tool"
    ]
    content: Optional[str] = None
    name: Optional[str] = None  # For tool messages
    tool_calls: Optional[list[ToolCall]] = (
        None  # For assistant messages
    )
    tool_call_id: Optional[str] = (
        None  # For tool messages
    )


@dataclass
class ToolCall:
    """Tool call within an assistant message."""

    id: str
    type: Literal["function"] = "function"
    function: FunctionCall = None


@dataclass
class FunctionCall:
    """Function call details."""

    name: str
    arguments: str  # JSON string, as per OpenAI spec


@dataclass
class SessionMetadata:
    """
    Session-level context that isn't in the conversation.
    """

    session_id: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None

    # Token tracking
    token_count: int = 0
    token_budget: Optional[int] = None

    # Cost tracking
    cost_usd: float = 0.0
    cost_budget_usd: Optional[float] = None

    # Permissions & compliance
    user_roles: list[str] = field(default_factory=list)
    user_region: Optional[str] = (
        None  # For GDPR, data residency
    )
    compliance_tags: list[str] = field(
        default_factory=list
    )

    # Timing
    started_at: datetime = field(
        default_factory=datetime.utcnow
    )

    # Extensible
    custom: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class EventPayload:
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


@dataclass
class PolicyEvent:
    """
    The complete event sent to policy servers.

    Structure:
    - Envelope: id, type, timestamp (when/what)
    - Messages: chat/completions format (conversation history)
    - Payload: event-specific data (the delta)
    - Metadata: session context (who/where/limits)
    """

    id: str
    type: EventType
    timestamp: datetime

    # Conversation context - chat/completions format
    messages: list[Message]

    # Event-specific payload
    payload: EventPayload

    # Session metadata
    metadata: SessionMetadata


# =============================================================================
# VERDICTS - What policies return
# =============================================================================


class Decision(str, Enum):
    """
    Policy decisions. Not just allow/deny!

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


@dataclass
class Modification:
    """How to modify the action/content."""

    target: Literal[
        "input", "tool_args", "llm_prompt", "output"
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
    path: Optional[str] = (
        None  # JSON path for surgical modifications
    )


@dataclass
class Escalation:
    """How to escalate to humans."""

    type: Literal[
        "human_confirm",
        "human_review",
        "abort",
        "fallback",
    ]
    prompt: Optional[str] = (
        None  # What to show the human
    )
    fallback_action: Optional[str] = (
        None  # What to do instead
    )
    timeout_ms: Optional[int] = (
        None  # How long to wait
    )

    # For structured confirmations
    options: Optional[list[str]] = (
        None  # e.g., ["Proceed", "Cancel", "Modify"]
    )


@dataclass
class Verdict:
    """Policy response."""

    decision: Decision
    confidence: float = 1.0
    reasoning: Optional[str] = None
    modifications: list[Modification] = field(
        default_factory=list
    )
    escalation: Optional[Escalation] = None
    policy_name: Optional[str] = None
    policy_version: Optional[str] = None
    evaluation_ms: Optional[float] = None
    trace: Optional[dict[str, Any]] = None

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
    def deny(
        cls, reasoning: str, confidence: float = 1.0
    ) -> Verdict:
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
    def observe(
        cls, reasoning: str = None, trace: dict = None
    ) -> Verdict:
        return cls(
            decision=Decision.OBSERVE,
            reasoning=reasoning,
            trace=trace,
        )


# =============================================================================
# CONTEXT CONTRACTS - What policies declare they need
# =============================================================================


@dataclass
class ContextRequirement:
    """
    A single context field requirement.

    Policies declare what they need, runtimes provide it.
    This enables portability - policies don't parse full agent state.
    """

    path: str  # e.g., "metadata.user_region"
    required: bool = (
        True  # If False, policy handles missing
    )
    description: Optional[str] = (
        None  # For documentation
    )


@dataclass
class PolicyDefinition:
    """
    How a policy server describes its policies to the runtime.
    This is sent during registration/handshake.
    """

    name: str
    version: str

    # What events this policy handles
    events: list[EventType]

    # What context it needs (the contract)
    context_requirements: list[ContextRequirement] = (
        field(default_factory=list)
    )

    # Execution characteristics
    blocking: bool = (
        True  # Must await vs fire-and-forget
    )
    timeout_ms: int = 1000  # Max evaluation time

    # Metadata
    description: Optional[str] = None
    author: Optional[str] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class PolicyManifest:
    """
    Complete manifest from a policy server.
    Sent during initialization handshake.
    """

    server_name: str
    server_version: str
    protocol_version: str = "0.2.0"

    policies: list[PolicyDefinition] = field(
        default_factory=list
    )

    # Server capabilities
    supports_batch: bool = (
        False  # Can handle multiple events at once
    )
    supports_streaming: bool = (
        False  # Can stream verdicts
    )

    # Documentation
    description: Optional[str] = None
    documentation_url: Optional[str] = None


# =============================================================================
# COMPOSITION - How multiple policies combine
# =============================================================================


class CompositionMode(str, Enum):
    """How to combine verdicts from multiple policies."""

    DENY_OVERRIDES = "deny_overrides"  # Any deny wins
    ALLOW_OVERRIDES = (
        "allow_overrides"  # Any allow wins (rare)
    )
    UNANIMOUS = "unanimous"  # All must agree
    FIRST_APPLICABLE = (
        "first_applicable"  # First non-observe wins
    )
    WEIGHTED = "weighted"  # Confidence-weighted voting


@dataclass
class CompositionConfig:
    """Configuration for verdict composition."""

    mode: CompositionMode = (
        CompositionMode.DENY_OVERRIDES
    )

    # Execution settings
    parallel: bool = (
        True  # Evaluate policies in parallel
    )
    timeout_ms: int = (
        500  # Total timeout for all policies
    )
    on_timeout: Decision = (
        Decision.ALLOW
    )  # Fail-open or fail-closed

    # Priority ordering (policy names, first = highest priority)
    priority: list[str] = field(default_factory=list)

    # For weighted mode
    weights: dict[str, float] = field(
        default_factory=dict
    )
