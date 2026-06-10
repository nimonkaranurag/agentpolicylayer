"""
LangGraph adapter: wrap a ``StateGraph``'s nodes with APL policy checkpoints.

This is the real integration path behind ``PolicyLayer.wrap`` (the old
``_wrap_langgraph`` stub returned the graph unwrapped). The five
one-class-per-file modules this replaces were a single cohesive concern, so they
live here together.

How wrapping works
------------------
A compiled-graph node is a ``StateNodeSpec`` dataclass whose ``runnable`` is a
LangGraph ``RunnableCallable`` (invoked via ``.invoke`` / ``.ainvoke``, not
``__call__``). We therefore wrap ``spec.runnable`` and rebuild the spec with
``dataclasses.replace`` — replacing the whole spec with a bare function (the old
behaviour) loses the spec's metadata and breaks compilation.

Each wrapped node runs *before* checkpoints, invokes the original node, then runs
*after* checkpoints. The wrapper exposes both a sync and an async form, so
``graph.ainvoke(...)`` evaluates policies natively on the running loop (no
``asyncio.run``, shared client sessions preserved) and only a purely synchronous
``graph.invoke(...)`` falls back to the blocking bridge below.

Verdicts are fail-closed by construction. ``DENY``/``ESCALATE`` raise
(:class:`~apl.layer.PolicyDenied` / :class:`~apl.layer.PolicyEscalation`) and
abort the node; a ``MODIFY`` is *applied* to the graph state in place via the
shared :func:`~apl.modifications.apply_operation` dispatcher (so ``redact`` /
``append`` actually change what the node sends/receives — the old adapter
ignored it), and a modification that can't be mapped to the state denies rather
than proceeding unmodified. The underlying ``PolicyLayer`` already denies on a
policy-server outage.

Loop affinity is handled in the client transports, not papered over here: the
HTTP client recreates its aiohttp session when evaluation runs on a different
loop than ``connect`` (so mixing sync ``invoke`` and async ``ainvoke`` is safe),
and the stdio client — whose subprocess genuinely can't move between loops —
fails closed with a clear message instead of crashing deep in asyncio.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import threading
import uuid
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Coroutine, Optional

from apl.adapters.base_adapter import BaseFrameworkAdapter
from apl.instrumentation.messages import LangChainMessageAdapter
from apl.layer import PolicyDenied, PolicyEscalation, PolicyLayer
from apl.logging import get_logger
from apl.modifications import apply_operation
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Message,
    SessionMetadata,
    Verdict,
)

logger = get_logger("adapter.langgraph")


# =============================================================================
# Running-loop-aware bridge
# =============================================================================


class _BridgeLoop:
    """
    A lazily-started, process-lived daemon event loop for driving coroutines from
    synchronous code.

    Using *one* persistent loop instead of a fresh ``asyncio.run`` per call is a
    correctness requirement, not an optimisation: a remote ``PolicyClient`` pins its
    aiohttp session to the loop it connected on, so a fresh-loop-per-node sync
    ``invoke`` would orphan that session after the first node and every later node would
    fail. One loop keeps the client usable across the whole run.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        loop, thread = self._ensure_started()
        if threading.current_thread() is thread:
            # Reentrant call from the bridge's own thread (pathological nested
            # wrapping): submitting back to this loop and blocking on the result
            # would deadlock, so drive a throwaway loop on a fresh thread instead.
            return _run_on_throwaway_thread(coro)
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    def _ensure_started(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop.run_forever,
                    name="apl-langgraph-bridge",
                    daemon=True,
                )
                self._thread.start()
            return self._loop, self._thread


_BRIDGE = _BridgeLoop()


def run_coroutine_blocking(coro: Coroutine[Any, Any, Any]) -> Any:
    """
    Run ``coro`` to completion from synchronous code and return its result.

    Drives the coroutine on the shared bridge loop (a daemon thread), so it works
    whether or not a loop is already running in the caller's thread (``ainvoke`` runs
    policies natively and never reaches here) and so a remote policy client's session
    survives across every node of a sync run. Exceptions raised by ``coro`` propagate to
    the caller.
    """
    return _BRIDGE.run(coro)


def _run_on_throwaway_thread(coro: Coroutine[Any, Any, Any]) -> Any:
    outcome: dict[str, Any] = {}

    def _drive() -> None:
        loop = asyncio.new_event_loop()
        try:
            outcome["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # re-raised on the caller's thread below
            outcome["error"] = exc
        finally:
            loop.close()

    worker = threading.Thread(
        target=_drive, name="apl-langgraph-bridge-reentrant", daemon=True
    )
    worker.start()
    worker.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


# =============================================================================
# Checkpoints
# =============================================================================


@dataclass
class PolicyCheckpoint:
    """
    Where, and in which direction, to evaluate one APL event around a node.

    ``node_name=None`` matches every node; ``before_node_execution`` selects the pre- or
    post-node evaluation phase.
    """

    event_type: EventType
    node_name: Optional[str] = None
    before_node_execution: bool = True


DEFAULT_CHECKPOINTS: list[PolicyCheckpoint] = [
    PolicyCheckpoint(EventType.INPUT_RECEIVED, before_node_execution=True),
    PolicyCheckpoint(EventType.TOOL_PRE_INVOKE, before_node_execution=True),
    PolicyCheckpoint(EventType.OUTPUT_PRE_SEND, before_node_execution=False),
]


# =============================================================================
# State extraction
# =============================================================================


class LangGraphStateExtractor:
    """
    Pull APL ``Message``s and ``SessionMetadata`` out of LangGraph state/config.
    """

    def __init__(self) -> None:
        self._message_adapter = LangChainMessageAdapter()

    def extract_messages(self, state: Any) -> list[Message]:
        raw_messages = self._raw_messages(state)
        if not raw_messages:
            return []
        return self._message_adapter.to_apl_messages(raw_messages)

    def resolve_session_id(self, config: Optional[dict]) -> str:
        """
        Resolve the session id for one node execution.

        LangGraph's ``configurable.thread_id`` is the only identifier that is stable
        across every node of a run (and across the turns of a conversation), so it is
        the session anchor. The previous implementation minted a fresh UUID on *every*
        checkpoint, so each event looked like a new session and any session-scoped
        policy (rate limits, budgets) was defeated. Without a ``thread_id`` (a one-shot
        invocation) we mint one id per node execution — shared by that node's
        before/after checkpoints — and rely on ``thread_id`` for cross-node continuity.
        """
        configurable = self._configurable(config)
        thread_id = configurable.get("thread_id")
        if thread_id:
            return str(thread_id)
        return uuid.uuid4().hex

    def extract_metadata(
        self,
        state: Any,
        config: Optional[dict],
        session_id: str,
    ) -> SessionMetadata:
        configurable = self._configurable(config)
        return SessionMetadata(
            session_id=session_id,
            user_id=configurable.get("user_id"),
        )

    @staticmethod
    def _configurable(config: Optional[dict]) -> dict:
        if isinstance(config, dict):
            value = config.get("configurable")
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _raw_messages(state: Any) -> Optional[list]:
        if isinstance(state, dict):
            return (
                state.get("messages")
                or state.get("chat_history")
                or state.get("history")
            )
        if isinstance(state, list):
            return state
        if hasattr(state, "messages"):
            return state.messages
        return None


# =============================================================================
# Checkpoint evaluation
# =============================================================================


# APL modification target -> the LangGraph state keys it can write back to (the
# first key already present wins, else the first listed). Mirrors the read keys in
# ``_build_payload`` so a MODIFY writes to the same place the payload was read from.
# Targets absent here (``input``/``llm_prompt``/``handoff_payload`` — messages and
# complex structures the adapter has no single state key for) are refused fail-closed.
_TARGET_STATE_KEYS: dict[str, tuple[str, ...]] = {
    "output": ("output", "response", "output_text"),
    "tool_args": ("tool_args", "tool_input"),
    "tool_result": ("tool_result", "result"),
    "plan": ("plan", "steps"),
}


class CheckpointEvaluator:
    """
    Build the event payload for a checkpoint, evaluate it, and enforce the verdict
    (fail-closed: ``DENY``/``ESCALATE`` raise).
    """

    def __init__(
        self,
        policy_layer: PolicyLayer,
        extractor: Optional[LangGraphStateExtractor] = None,
    ) -> None:
        self._policy_layer = policy_layer
        self._extractor = extractor or LangGraphStateExtractor()

    async def evaluate(
        self,
        checkpoint: PolicyCheckpoint,
        state: Any,
        config: Optional[dict],
        node_name: str,
        session_id: str,
    ) -> Verdict:
        messages = self._extractor.extract_messages(state)
        metadata = self._extractor.extract_metadata(state, config, session_id)
        payload = self._build_payload(checkpoint.event_type, state, node_name, messages)

        verdict = await self._policy_layer.evaluate(
            event_type=checkpoint.event_type,
            messages=messages,
            payload=payload,
            metadata=metadata,
        )

        logger.debug(
            f"Checkpoint {checkpoint.event_type.value} at {node_name}: "
            f"{verdict.decision.value}"
        )

        if verdict.decision == Decision.DENY:
            raise PolicyDenied(verdict)
        if verdict.decision == Decision.ESCALATE:
            raise PolicyEscalation(verdict)
        if verdict.decision == Decision.MODIFY:
            self._apply_modifications(verdict, state, node_name)
        return verdict

    def _apply_modifications(
        self,
        verdict: Verdict,
        state: Any,
        node_name: str,
    ) -> None:
        """
        Apply a ``MODIFY`` verdict's modifications to the graph state in place.

        Each modification is mapped to the matching state key and routed through the
        shared :func:`~apl.modifications.apply_operation` dispatcher, so ``redact`` /
        ``append`` / ``patch`` mean the same thing here as everywhere else and actually
        change what the node sends/receives — the old adapter let ``MODIFY`` through
        untouched, a silent no-op.

        Fails **closed**: if a modification targets something the adapter cannot map to
        the (dict) state, or the dispatcher rejects it, the action is *denied* rather
        than allowed to proceed unmodified — letting an action through without the
        modification a policy demanded is the fail-open trap a guardrails layer must not
        have.
        """
        if not isinstance(state, dict):
            raise PolicyDenied(
                Verdict.deny(
                    reasoning=(
                        f"Policy returned MODIFY at node {node_name!r} but the graph "
                        f"state is {type(state).__name__}, not a dict APL can modify; "
                        "denying."
                    )
                )
            )

        for modification in verdict.modifications:
            state_keys = _TARGET_STATE_KEYS.get(modification.target)
            if state_keys is None:
                raise PolicyDenied(
                    Verdict.deny(
                        reasoning=(
                            f"Policy returned MODIFY target={modification.target!r} at "
                            f"node {node_name!r}, which the LangGraph adapter cannot map "
                            "to graph state; denying rather than proceeding unmodified."
                        )
                    )
                )
            key = next((k for k in state_keys if k in state), state_keys[0])
            try:
                state[key] = apply_operation(state.get(key), modification)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise PolicyDenied(
                    Verdict.deny(
                        reasoning=(
                            f"Policy MODIFY ({modification.operation} "
                            f"{modification.target}) at node {node_name!r} could not be "
                            f"applied: {exc}"
                        )
                    )
                ) from exc

    def _build_payload(
        self,
        event_type: EventType,
        state: Any,
        node_name: str,
        messages: list[Message],
    ) -> EventPayload:
        """
        Populate the payload fields that match ``event_type``.

        Each event type carries different fields (see :class:`~apl.types.EventPayload`);
        populating the wrong ones — or, as before, leaving every field empty for all but
        two event types — hands policies a payload that doesn't match the event they
        subscribed to. The conversation is always available via ``messages`` regardless.
        """
        data = state if isinstance(state, dict) else {}

        if event_type in (EventType.TOOL_PRE_INVOKE, EventType.TOOL_POST_INVOKE):
            return EventPayload(
                tool_name=data.get("tool_name") or node_name,
                tool_args=data.get("tool_args") or data.get("tool_input"),
                tool_result=data.get("tool_result") or data.get("result"),
            )
        if event_type in (EventType.LLM_PRE_REQUEST, EventType.LLM_POST_RESPONSE):
            return EventPayload(
                llm_model=data.get("model") or data.get("llm_model"),
                llm_prompt=messages or None,
                llm_response=self._last_assistant(messages),
            )
        if event_type == EventType.PLAN_PROPOSED:
            return EventPayload(plan=data.get("plan") or data.get("steps"))
        if event_type in (
            EventType.AGENT_PRE_HANDOFF,
            EventType.AGENT_POST_HANDOFF,
        ):
            return EventPayload(
                target_agent=data.get("target_agent") or data.get("next"),
                source_agent=data.get("source_agent") or node_name,
            )
        if event_type == EventType.OUTPUT_PRE_SEND:
            return EventPayload(output_text=self._output_text(data, messages))

        # INPUT_RECEIVED / INPUT_VALIDATED / anything else: the input is the
        # conversation, carried by ``messages``; no payload delta to add.
        return EventPayload()

    @staticmethod
    def _last_assistant(messages: list[Message]) -> Optional[Message]:
        for message in reversed(messages):
            if message.role == "assistant":
                return message
        return None

    @staticmethod
    def _output_text(data: dict, messages: list[Message]) -> Optional[str]:
        text = data.get("output") or data.get("response") or data.get("output_text")
        if text:
            return text
        for message in reversed(messages):
            if message.role == "assistant":
                return message.content
        return None


# =============================================================================
# Node wrapping
# =============================================================================

NodeCallable = Callable[..., Any]


class NodeWrapper:
    """
    Wrap a single graph node so APL checkpoints run around its execution.

    Handles both a real LangGraph ``StateNodeSpec`` (wraps ``spec.runnable`` and
    rebuilds the spec) and a plain callable (for graph-likes / tests). The session id is
    resolved once per node execution so a node's before/after checkpoints share it.
    """

    def __init__(
        self,
        policy_layer: PolicyLayer,
        checkpoints: list[PolicyCheckpoint],
    ) -> None:
        self._extractor = LangGraphStateExtractor()
        self._evaluator = CheckpointEvaluator(policy_layer, self._extractor)
        self._checkpoints = checkpoints

    def wrap(self, node_name: str, node_value: Any) -> Any:
        if hasattr(node_value, "runnable"):
            return self._wrap_spec(node_name, node_value)
        if callable(node_value):
            return self._wrap_callable(node_name, node_value)
        # Refuse to silently leave a node unguarded (fail-closed): a node we
        # cannot wrap would run with no policy enforcement at all.
        raise TypeError(
            f"Cannot wrap node {node_name!r}: expected a LangGraph node spec or "
            f"a callable, got {type(node_value).__name__}"
        )

    def _wrap_spec(self, node_name: str, spec: Any) -> Any:
        # Imported lazily: only reachable when a real LangGraph graph is wrapped.
        from langgraph.utils.runnable import RunnableCallable

        original = spec.runnable

        async def ainvoke_original(state: Any, config: Optional[dict]) -> Any:
            return await original.ainvoke(state, config)

        sync_node, async_node = self._build_wrappers(node_name, ainvoke_original)
        wrapped = RunnableCallable(
            sync_node,
            async_node,
            name=getattr(original, "name", node_name),
        )
        return replace(spec, runnable=wrapped)

    def _wrap_callable(self, node_name: str, func: NodeCallable) -> NodeCallable:
        accepts_config = self._accepts_config(func)

        async def ainvoke_original(state: Any, config: Optional[dict]) -> Any:
            result = func(state, config) if accepts_config else func(state)
            if inspect.isawaitable(result):
                return await result
            return result

        sync_node, async_node = self._build_wrappers(node_name, ainvoke_original)
        return async_node if inspect.iscoroutinefunction(func) else sync_node

    def _build_wrappers(
        self,
        node_name: str,
        ainvoke_original: Callable[[Any, Optional[dict]], Awaitable[Any]],
    ) -> tuple[NodeCallable, NodeCallable]:
        async def flow(state: Any, config: Optional[dict]) -> Any:
            session_id = self._extractor.resolve_session_id(config)
            await self._run_phase(state, config, node_name, session_id, before=True)
            result = await ainvoke_original(state, config)
            # ``result or state``: a node's return is a partial state *delta*; an
            # empty/None delta falls back to the input state so the after-phase
            # still has the fuller context to inspect (the safer default).
            await self._run_phase(
                result or state, config, node_name, session_id, before=False
            )
            return result

        # ``config`` is intentionally unannotated: LangGraph injects its
        # ``RunnableConfig`` by parameter *name*, and warns if it is annotated
        # as anything other than ``RunnableConfig`` (e.g. ``Optional[dict]``).
        def sync_node(state: Any, config=None) -> Any:
            return run_coroutine_blocking(flow(state, config))

        async def async_node(state: Any, config=None) -> Any:
            return await flow(state, config)

        return sync_node, async_node

    async def _run_phase(
        self,
        state: Any,
        config: Optional[dict],
        node_name: str,
        session_id: str,
        before: bool,
    ) -> None:
        for checkpoint in self._checkpoints:
            if self._matches(checkpoint, node_name, before):
                await self._evaluator.evaluate(
                    checkpoint, state, config, node_name, session_id
                )

    @staticmethod
    def _matches(checkpoint: PolicyCheckpoint, node_name: str, before: bool) -> bool:
        if checkpoint.before_node_execution != before:
            return False
        return checkpoint.node_name is None or checkpoint.node_name == node_name

    @staticmethod
    def _accepts_config(func: NodeCallable) -> bool:
        try:
            params = inspect.signature(func).parameters
        except (TypeError, ValueError):
            return False
        if "config" in params:
            return True
        # A node taking (state, config) positionally, or **kwargs.
        positional = [
            p
            for p in params.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        has_var_keyword = any(p.kind == p.VAR_KEYWORD for p in params.values())
        return len(positional) >= 2 or has_var_keyword


# =============================================================================
# Public adapter
# =============================================================================


class APLGraphWrapper(BaseFrameworkAdapter):
    """
    Wrap a LangGraph ``StateGraph`` so its nodes are guarded by APL policies.

    The real implementation of the framework-adapter SPI: it subclasses
    :class:`~apl.adapters.base_adapter.BaseFrameworkAdapter` and implements
    ``framework_name`` / ``is_available`` / ``wrap`` so ``wrap()`` can dispatch
    through the registry instead of the abstraction sitting unused.
    """

    def __init__(self, policy_layer: Optional[PolicyLayer] = None) -> None:
        super().__init__(policy_layer or PolicyLayer())
        self._checkpoints: list[PolicyCheckpoint] = []

    @property
    def framework_name(self) -> str:
        return "langgraph"

    @staticmethod
    def is_available() -> bool:
        return importlib.util.find_spec("langgraph") is not None

    def add_server(self, uri: str) -> "APLGraphWrapper":
        self.policy_layer.add_server(uri)
        return self

    def add_checkpoint(
        self,
        event_type: str | EventType,
        node_name: Optional[str] = None,
        before: bool = True,
    ) -> "APLGraphWrapper":
        self._checkpoints.append(
            PolicyCheckpoint(
                event_type=EventType(event_type),
                node_name=node_name,
                before_node_execution=before,
            )
        )
        return self

    def wrap(self, agent: Any) -> Any:
        if not self._is_state_graph(agent):
            # Loud and typed beats a silent no-op: the old stub returned
            # the graph unwrapped, so policies never ran.
            raise TypeError(
                "APLGraphWrapper.wrap expected a LangGraph StateGraph "
                "(with .nodes/.add_node/.add_edge); got "
                f"{type(agent).__name__}"
            )

        checkpoints = self._checkpoints or DEFAULT_CHECKPOINTS
        node_wrapper = NodeWrapper(self.policy_layer, checkpoints)

        original_nodes = dict(agent.nodes)
        for node_name, node_value in original_nodes.items():
            agent.nodes[node_name] = node_wrapper.wrap(node_name, node_value)

        logger.info(
            f"Wrapped {len(original_nodes)} node(s) with APL policy checkpoints"
        )
        return agent

    @staticmethod
    def _is_state_graph(obj: Any) -> bool:
        return all(hasattr(obj, attr) for attr in ("nodes", "add_node", "add_edge"))


def create_apl_graph(graph: Any, policy_servers: list[str]) -> Any:
    """
    Convenience factory: wrap ``graph`` after adding each policy-server URI.
    """
    wrapper = APLGraphWrapper()
    for uri in policy_servers:
        wrapper.add_server(uri)
    return wrapper.wrap(graph)


__all__ = [
    "APLGraphWrapper",
    "CheckpointEvaluator",
    "LangGraphStateExtractor",
    "NodeWrapper",
    "PolicyCheckpoint",
    "create_apl_graph",
    "run_coroutine_blocking",
]
