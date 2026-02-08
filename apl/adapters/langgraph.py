"""
APL LangGraph Adapter

Seamlessly integrate APL policies into LangGraph workflows.

Features:
- Automatic policy evaluation at graph checkpoints
- Tool call interception
- State-aware context building
- Human-in-the-loop escalation support

Usage:
    from langgraph.graph import StateGraph
    from apl.adapters.langgraph import APLGraphWrapper

    graph = StateGraph(...)
    # ... build your graph ...

    wrapper = APLGraphWrapper()
    wrapper.add_server("stdio://./policies/pii_filter.py")

    wrapped_graph = wrapper.wrap(graph)
    # Use wrapped_graph normally - policies are evaluated automatically

Note: This adapter requires langgraph to be installed separately.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Optional

from ..layer import (
    PolicyDenied,
    PolicyEscalation,
    PolicyLayer,
)
from ..logging import get_logger
from ..types import (
    Decision,
    EventPayload,
    EventType,
    Message,
    SessionMetadata,
)

logger = get_logger("langgraph")


# =============================================================================
# STATE EXTRACTION
# =============================================================================


def extract_messages_from_state(
    state: Any,
) -> list[Message]:
    """
    Extract chat messages from LangGraph state.

    Handles common state patterns:
    - {"messages": [...]} - Standard message list
    - {"chat_history": [...]} - Alternative key
    - Direct list of messages

    Args:
        state: LangGraph state object

    Returns:
        List of APL Message objects
    """
    messages = []

    # Try common patterns
    raw_messages = None

    if isinstance(state, dict):
        raw_messages = (
            state.get("messages")
            or state.get("chat_history")
            or state.get("history")
        )
    elif isinstance(state, list):
        raw_messages = state
    elif hasattr(state, "messages"):
        raw_messages = state.messages

    if not raw_messages:
        return messages

    for msg in raw_messages:
        # Handle different message formats
        if isinstance(msg, dict):
            messages.append(
                Message(
                    role=msg.get("role", "user"),
                    content=msg.get("content"),
                    name=msg.get("name"),
                    tool_call_id=msg.get("tool_call_id"),
                )
            )
        elif hasattr(msg, "type") and hasattr(
            msg, "content"
        ):
            # LangChain message format
            role_map = {
                "human": "user",
                "ai": "assistant",
                "system": "system",
                "tool": "tool",
            }
            role = role_map.get(msg.type, msg.type)
            messages.append(
                Message(
                    role=role,
                    content=(
                        msg.content
                        if isinstance(msg.content, str)
                        else str(msg.content)
                    ),
                )
            )
        elif hasattr(msg, "role") and hasattr(
            msg, "content"
        ):
            messages.append(
                Message(
                    role=msg.role,
                    content=msg.content,
                )
            )

    return messages


def extract_metadata_from_state(
    state: Any, config: Optional[dict] = None
) -> SessionMetadata:
    """
    Extract session metadata from state and config.

    Args:
        state: LangGraph state object
        config: LangGraph config dict

    Returns:
        SessionMetadata object
    """
    session_id = str(uuid.uuid4())
    user_id = None

    if config:
        session_id = config.get("configurable", {}).get(
            "thread_id", session_id
        )
        user_id = config.get("configurable", {}).get(
            "user_id"
        )

    return SessionMetadata(
        session_id=session_id,
        user_id=user_id,
    )


# =============================================================================
# GRAPH WRAPPER
# =============================================================================


@dataclass
class PolicyCheckpoint:
    """Configuration for a policy checkpoint in the graph."""

    event_type: EventType
    node_name: Optional[str] = None
    before: bool = True  # Before or after node execution


class APLGraphWrapper:
    """
    Wrapper that adds APL policy evaluation to LangGraph graphs.

    Usage:
        wrapper = APLGraphWrapper()
        wrapper.add_server("stdio://./my_policy.py")

        # Wrap entire graph
        wrapped = wrapper.wrap(graph)

        # Or wrap specific nodes
        @wrapper.policy_node("tool.pre_invoke")
        def tool_node(state):
            ...
    """

    def __init__(
        self, policy_layer: Optional[PolicyLayer] = None
    ):
        """
        Initialize the wrapper.

        Args:
            policy_layer: Existing PolicyLayer, or None to create new one
        """
        self._layer = policy_layer or PolicyLayer()
        self._checkpoints: list[PolicyCheckpoint] = []

    def add_server(self, uri: str) -> "APLGraphWrapper":
        """
        Add a policy server.

        Args:
            uri: Policy server URI

        Returns:
            self for chaining
        """
        self._layer.add_server(uri)
        return self

    def add_checkpoint(
        self,
        event_type: str | EventType,
        node_name: Optional[str] = None,
        before: bool = True,
    ) -> "APLGraphWrapper":
        """
        Add a policy checkpoint.

        Args:
            event_type: Event type to evaluate
            node_name: Specific node to check (None for all)
            before: Evaluate before (True) or after (False) node

        Returns:
            self for chaining
        """
        if isinstance(event_type, str):
            event_type = EventType(event_type)

        self._checkpoints.append(
            PolicyCheckpoint(
                event_type=event_type,
                node_name=node_name,
                before=before,
            )
        )
        return self

    def wrap(self, graph: Any) -> Any:
        """
        Wrap a LangGraph StateGraph with policy evaluation.

        This intercepts node execution and evaluates policies at checkpoints.

        Args:
            graph: LangGraph StateGraph instance

        Returns:
            Wrapped graph that evaluates policies
        """
        # Check if it's a StateGraph
        if not hasattr(graph, "nodes") or not hasattr(
            graph, "add_node"
        ):
            logger.warning(
                "Object doesn't appear to be a LangGraph StateGraph"
            )
            return graph

        # Default checkpoints if none specified
        if not self._checkpoints:
            self._checkpoints = [
                PolicyCheckpoint(
                    EventType.INPUT_RECEIVED, before=True
                ),
                PolicyCheckpoint(
                    EventType.TOOL_PRE_INVOKE, before=True
                ),
                PolicyCheckpoint(
                    EventType.OUTPUT_PRE_SEND, before=False
                ),
            ]

        # Wrap each node
        original_nodes = dict(graph.nodes)

        for node_name, node_func in original_nodes.items():
            wrapped = self._wrap_node(node_name, node_func)
            graph.nodes[node_name] = wrapped

        logger.info(
            f"Wrapped {len(original_nodes)} nodes with APL policies"
        )

        return graph

    def _wrap_node(
        self, node_name: str, node_func: Callable
    ) -> Callable:
        """Wrap a single node function."""

        @wraps(node_func)
        async def async_wrapper(state, config=None):
            # Check "before" policies
            for checkpoint in self._checkpoints:
                if (
                    checkpoint.before
                    and self._checkpoint_applies(
                        checkpoint, node_name
                    )
                ):
                    await self._evaluate_checkpoint(
                        checkpoint, state, config, node_name
                    )

            # Execute original node
            if asyncio.iscoroutinefunction(node_func):
                result = (
                    await node_func(state, config)
                    if config
                    else await node_func(state)
                )
            else:
                result = (
                    node_func(state, config)
                    if config
                    else node_func(state)
                )

            # Check "after" policies
            for checkpoint in self._checkpoints:
                if (
                    not checkpoint.before
                    and self._checkpoint_applies(
                        checkpoint, node_name
                    )
                ):
                    await self._evaluate_checkpoint(
                        checkpoint,
                        result or state,
                        config,
                        node_name,
                    )

            return result

        @wraps(node_func)
        def sync_wrapper(state, config=None):
            return asyncio.run(async_wrapper(state, config))

        # Return appropriate wrapper
        if asyncio.iscoroutinefunction(node_func):
            return async_wrapper
        else:
            return sync_wrapper

    def _checkpoint_applies(
        self, checkpoint: PolicyCheckpoint, node_name: str
    ) -> bool:
        """Check if a checkpoint applies to a node."""
        if checkpoint.node_name is None:
            return True
        return checkpoint.node_name == node_name

    async def _evaluate_checkpoint(
        self,
        checkpoint: PolicyCheckpoint,
        state: Any,
        config: Optional[dict],
        node_name: str,
    ):
        """Evaluate policies at a checkpoint."""
        messages = extract_messages_from_state(state)
        metadata = extract_metadata_from_state(
            state, config
        )

        # Build payload based on event type
        payload = EventPayload()

        if (
            checkpoint.event_type
            == EventType.TOOL_PRE_INVOKE
        ):
            # Try to extract tool info from state
            if isinstance(state, dict):
                payload.tool_name = (
                    state.get("tool_name") or node_name
                )
                payload.tool_args = state.get(
                    "tool_args"
                ) or state.get("tool_input")

        elif (
            checkpoint.event_type
            == EventType.OUTPUT_PRE_SEND
        ):
            # Try to extract output
            if isinstance(state, dict):
                payload.output_text = state.get(
                    "output"
                ) or state.get("response")
            elif messages:
                last_assistant = [
                    m
                    for m in messages
                    if m.role == "assistant"
                ]
                if last_assistant:
                    payload.output_text = last_assistant[
                        -1
                    ].content

        # Evaluate
        verdict = await self._layer.evaluate(
            event_type=checkpoint.event_type,
            messages=messages,
            payload=payload,
            metadata=metadata,
        )

        logger.debug(
            f"Checkpoint {checkpoint.event_type.value} at {node_name}: {verdict.decision.value}"
        )

        # Handle verdict
        if verdict.decision == Decision.DENY:
            raise PolicyDenied(verdict)

        if verdict.decision == Decision.ESCALATE:
            raise PolicyEscalation(verdict)

    def policy_node(self, event_type: str | EventType):
        """
        Decorator to add policy evaluation to a specific node.

        Usage:
            @wrapper.policy_node("tool.pre_invoke")
            def my_tool_node(state):
                ...
        """
        if isinstance(event_type, str):
            event_type = EventType(event_type)

        def decorator(func):
            @wraps(func)
            async def async_wrapper(state, config=None):
                messages = extract_messages_from_state(
                    state
                )
                metadata = extract_metadata_from_state(
                    state, config
                )

                verdict = await self._layer.evaluate(
                    event_type=event_type,
                    messages=messages,
                    payload=EventPayload(),
                    metadata=metadata,
                )

                if verdict.decision == Decision.DENY:
                    raise PolicyDenied(verdict)

                if verdict.decision == Decision.ESCALATE:
                    raise PolicyEscalation(verdict)

                if asyncio.iscoroutinefunction(func):
                    return (
                        await func(state, config)
                        if config
                        else await func(state)
                    )
                else:
                    return (
                        func(state, config)
                        if config
                        else func(state)
                    )

            return async_wrapper

        return decorator


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_apl_graph(
    graph: Any,
    policy_servers: list[str],
) -> Any:
    """
    Convenience function to wrap a graph with policies.

    Args:
        graph: LangGraph StateGraph
        policy_servers: List of policy server URIs

    Returns:
        Wrapped graph

    Example:
        from apl.adapters.langgraph import create_apl_graph

        wrapped = create_apl_graph(
            my_graph,
            policy_servers=[
                "stdio://./policies/pii_filter.py",
                "https://policies.corp.com/compliance",
            ]
        )
    """
    wrapper = APLGraphWrapper()

    for uri in policy_servers:
        wrapper.add_server(uri)

    return wrapper.wrap(graph)
