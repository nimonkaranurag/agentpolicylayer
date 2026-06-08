from __future__ import annotations

import asyncio
import importlib.util
import threading
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from apl.adapters import APLGraphWrapper, BaseFrameworkAdapter, create_apl_graph
from apl.adapters.langgraph import (
    CheckpointEvaluator,
    LangGraphStateExtractor,
    NodeWrapper,
    PolicyCheckpoint,
    run_coroutine_blocking,
)
from apl.layer import PolicyDenied, PolicyEscalation
from apl.types import Decision, EventType, Verdict

_HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None
requires_langgraph = pytest.mark.skipif(
    not _HAS_LANGGRAPH, reason="requires the optional 'langgraph' extra"
)


class FakeLayer:
    """
    Minimal ``PolicyLayer`` stand-in: records ``evaluate`` calls and returns a
    configurable verdict (optionally per event type).
    """

    def __init__(
        self,
        verdict: Optional[Verdict] = None,
        by_event: Optional[dict] = None,
    ) -> None:
        self.calls: list[SimpleNamespace] = []
        self._verdict = verdict or Verdict.allow()
        self._by_event = by_event or {}

    async def evaluate(
        self,
        event_type: Any,
        messages: Any = None,
        payload: Any = None,
        metadata: Any = None,
    ) -> Verdict:
        self.calls.append(
            SimpleNamespace(
                event_type=event_type,
                messages=messages or [],
                payload=payload,
                metadata=metadata,
            )
        )
        return self._by_event.get(event_type, self._verdict)


class TestRunCoroutineBlocking:
    def test_runs_without_a_running_loop(self) -> None:
        async def coro() -> int:
            return 42

        assert run_coroutine_blocking(coro()) == 42

    async def test_runs_from_within_a_running_loop(self) -> None:
        main_thread = threading.current_thread().name
        captured: dict[str, str] = {}

        async def coro() -> str:
            captured["thread"] = threading.current_thread().name
            return "ok"

        # We are inside the event loop here; the bridge must not call
        # asyncio.run (which would raise) but drive a private loop off-thread.
        result = run_coroutine_blocking(coro())
        assert result == "ok"
        assert captured["thread"] != main_thread

    def test_propagates_exceptions(self) -> None:
        async def boom() -> None:
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            run_coroutine_blocking(boom())

    async def test_propagates_exceptions_from_running_loop(self) -> None:
        # The worker-thread path must re-raise on the caller's thread, not hang:
        # a policy that raises inside the sync bridge has to surface.
        async def boom() -> None:
            raise ValueError("kaboom-off-thread")

        with pytest.raises(ValueError, match="kaboom-off-thread"):
            run_coroutine_blocking(boom())

    def test_reuses_one_loop_across_calls(self) -> None:
        # A remote client pins its session to the loop it connected on, so the
        # bridge must reuse ONE loop across nodes; a fresh loop per call would
        # orphan that session after the first node.
        loops: list[Any] = []

        async def capture() -> None:
            loops.append(asyncio.get_running_loop())

        run_coroutine_blocking(capture())
        run_coroutine_blocking(capture())
        assert loops[0] is loops[1]

    def test_reentrant_call_from_bridge_thread_does_not_deadlock(self) -> None:
        # A nested blocking call made from within the bridge loop's own thread
        # must fall back to a throwaway loop rather than deadlock on itself.
        async def inner() -> int:
            return 99

        async def outer() -> int:
            # Runs on the bridge thread; the nested call re-enters the bridge.
            return run_coroutine_blocking(inner())

        assert run_coroutine_blocking(outer()) == 99

    def test_reentrant_call_propagates_exception(self) -> None:
        async def inner() -> None:
            raise ValueError("nested-boom")

        async def outer() -> None:
            return run_coroutine_blocking(inner())

        with pytest.raises(ValueError, match="nested-boom"):
            run_coroutine_blocking(outer())


class TestLangGraphStateExtractor:
    def test_extract_messages_from_dict(self) -> None:
        extractor = LangGraphStateExtractor()
        messages = extractor.extract_messages(
            {"messages": [{"role": "user", "content": "hi"}]}
        )
        assert [m.content for m in messages] == ["hi"]

    def test_extract_messages_empty(self) -> None:
        assert LangGraphStateExtractor().extract_messages({}) == []

    def test_extract_messages_from_list_state(self) -> None:
        messages = LangGraphStateExtractor().extract_messages(
            [{"role": "user", "content": "hey"}]
        )
        assert [m.content for m in messages] == ["hey"]

    def test_extract_messages_from_object_with_messages_attr(self) -> None:
        state = SimpleNamespace(messages=[{"role": "user", "content": "yo"}])
        messages = LangGraphStateExtractor().extract_messages(state)
        assert [m.content for m in messages] == ["yo"]

    def test_resolve_session_id_prefers_thread_id(self) -> None:
        extractor = LangGraphStateExtractor()
        config = {"configurable": {"thread_id": "T-1"}}
        assert extractor.resolve_session_id(config) == "T-1"
        # Stable across calls (the bug was a fresh UUID per checkpoint).
        assert extractor.resolve_session_id(config) == "T-1"

    def test_resolve_session_id_without_thread_id_is_nonempty(self) -> None:
        session_id = LangGraphStateExtractor().resolve_session_id(None)
        assert isinstance(session_id, str) and session_id

    def test_extract_metadata_uses_session_id_and_user(self) -> None:
        metadata = LangGraphStateExtractor().extract_metadata(
            {}, {"configurable": {"user_id": "u1"}}, "S-9"
        )
        assert metadata.session_id == "S-9"
        assert metadata.user_id == "u1"


class TestCheckpointEvaluator:
    async def test_deny_raises_policy_denied(self) -> None:
        evaluator = CheckpointEvaluator(FakeLayer(Verdict.deny(reasoning="no")))
        with pytest.raises(PolicyDenied):
            await evaluator.evaluate(
                PolicyCheckpoint(EventType.INPUT_RECEIVED), {}, None, "n", "S"
            )

    async def test_escalate_raises_policy_escalation(self) -> None:
        evaluator = CheckpointEvaluator(
            FakeLayer(Verdict.escalate("human_review", reasoning="esc"))
        )
        with pytest.raises(PolicyEscalation):
            await evaluator.evaluate(
                PolicyCheckpoint(EventType.INPUT_RECEIVED), {}, None, "n", "S"
            )

    async def test_allow_returns_verdict(self) -> None:
        verdict = await CheckpointEvaluator(FakeLayer()).evaluate(
            PolicyCheckpoint(EventType.INPUT_RECEIVED), {}, None, "n", "S"
        )
        assert verdict.decision == Decision.ALLOW

    async def test_session_id_threaded_into_metadata(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.INPUT_RECEIVED), {}, None, "n", "SID-7"
        )
        assert layer.calls[0].metadata.session_id == "SID-7"

    async def test_payload_matches_output_event(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.OUTPUT_PRE_SEND),
            {"output": "hello"},
            None,
            "n",
            "S",
        )
        assert layer.calls[0].payload.output_text == "hello"

    async def test_payload_matches_tool_event(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.TOOL_PRE_INVOKE),
            {"tool_name": "search", "tool_args": {"q": "x"}},
            None,
            "node",
            "S",
        )
        payload = layer.calls[0].payload
        assert payload.tool_name == "search"
        assert payload.tool_args == {"q": "x"}

    async def test_tool_name_defaults_to_node_name(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.TOOL_PRE_INVOKE), {}, None, "mytool", "S"
        )
        assert layer.calls[0].payload.tool_name == "mytool"

    async def test_payload_matches_llm_event(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.LLM_PRE_REQUEST),
            {"messages": [{"role": "user", "content": "q"}]},
            None,
            "n",
            "S",
        )
        payload = layer.calls[0].payload
        assert payload.llm_prompt and payload.llm_prompt[0].content == "q"

    async def test_input_event_has_empty_payload_but_carries_messages(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.INPUT_RECEIVED),
            {"messages": [{"role": "user", "content": "hi"}]},
            None,
            "n",
            "S",
        )
        call = layer.calls[0]
        assert call.payload.output_text is None
        assert call.payload.tool_name is None
        assert call.messages and call.messages[0].content == "hi"

    async def test_payload_matches_plan_event(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.PLAN_PROPOSED),
            {"plan": ["a", "b"]},
            None,
            "n",
            "S",
        )
        assert layer.calls[0].payload.plan == ["a", "b"]

    async def test_payload_matches_handoff_event(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.AGENT_PRE_HANDOFF),
            {"target_agent": "billing"},
            None,
            "router",
            "S",
        )
        payload = layer.calls[0].payload
        assert payload.target_agent == "billing"
        assert payload.source_agent == "router"

    async def test_payload_llm_response_from_last_assistant(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.LLM_POST_RESPONSE),
            {
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "content": "a"},
                ]
            },
            None,
            "n",
            "S",
        )
        assert layer.calls[0].payload.llm_response.content == "a"

    async def test_output_text_falls_back_to_last_assistant_message(self) -> None:
        layer = FakeLayer()
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.OUTPUT_PRE_SEND),
            {"messages": [{"role": "assistant", "content": "final answer"}]},
            None,
            "n",
            "S",
        )
        assert layer.calls[0].payload.output_text == "final answer"


class TestCheckpointEvaluatorModify:
    """
    A MODIFY verdict must actually change the graph state, or fail closed.
    """

    async def test_replace_output_in_state(self) -> None:
        layer = FakeLayer(
            Verdict.modify(target="output", operation="replace", value="[REDACTED]")
        )
        state = {"output": "SECRET"}
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.OUTPUT_PRE_SEND), state, None, "n", "S"
        )
        assert state["output"] == "[REDACTED]"

    async def test_redact_routes_through_shared_dispatcher(self) -> None:
        # operation='redact' with no value uses the dispatcher's DEFAULT_REDACTION,
        # proving MODIFY honours the operation (not a degraded 'replace').
        layer = FakeLayer(
            Verdict.modify(target="output", operation="redact", value=None)
        )
        state = {"output": "SECRET"}
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.OUTPUT_PRE_SEND), state, None, "n", "S"
        )
        assert state["output"] == "[REDACTED]"

    async def test_append_to_output(self) -> None:
        layer = FakeLayer(
            Verdict.modify(target="output", operation="append", value=" [edited]")
        )
        state = {"output": "hello"}
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.OUTPUT_PRE_SEND), state, None, "n", "S"
        )
        assert state["output"] == "hello [edited]"

    async def test_modify_tool_args(self) -> None:
        layer = FakeLayer(
            Verdict.modify(
                target="tool_args", operation="replace", value={"safe": True}
            )
        )
        state = {"tool_args": {"danger": True}}
        await CheckpointEvaluator(layer).evaluate(
            PolicyCheckpoint(EventType.TOOL_PRE_INVOKE), state, None, "n", "S"
        )
        assert state["tool_args"] == {"safe": True}

    async def test_unmappable_target_fails_closed(self) -> None:
        layer = FakeLayer(
            Verdict.modify(target="llm_prompt", operation="replace", value="x")
        )
        with pytest.raises(PolicyDenied, match="cannot map"):
            await CheckpointEvaluator(layer).evaluate(
                PolicyCheckpoint(EventType.OUTPUT_PRE_SEND),
                {"output": "x"},
                None,
                "n",
                "S",
            )

    async def test_non_dict_state_fails_closed(self) -> None:
        layer = FakeLayer(
            Verdict.modify(target="output", operation="replace", value="x")
        )
        with pytest.raises(PolicyDenied, match="not a dict"):
            await CheckpointEvaluator(layer).evaluate(
                PolicyCheckpoint(EventType.OUTPUT_PRE_SEND),
                "a bare string",
                None,
                "n",
                "S",
            )

    async def test_dispatcher_error_fails_closed(self) -> None:
        # 'patch' with no path is rejected by the shared dispatcher -> deny.
        layer = FakeLayer(Verdict.modify(target="output", operation="patch", value="x"))
        with pytest.raises(PolicyDenied, match="could not be applied"):
            await CheckpointEvaluator(layer).evaluate(
                PolicyCheckpoint(EventType.OUTPUT_PRE_SEND),
                {"output": "hello"},
                None,
                "n",
                "S",
            )


class TestNodeWrapperCallablePath:
    def test_sync_node_fires_before_and_after(self) -> None:
        layer = FakeLayer()
        checkpoints = [
            PolicyCheckpoint(EventType.INPUT_RECEIVED, before_node_execution=True),
            PolicyCheckpoint(EventType.OUTPUT_PRE_SEND, before_node_execution=False),
        ]
        wrapped = NodeWrapper(layer, checkpoints).wrap("n", lambda s: {"value": 1})

        assert wrapped({"value": 0}) == {"value": 1}
        assert [c.event_type for c in layer.calls] == [
            EventType.INPUT_RECEIVED,
            EventType.OUTPUT_PRE_SEND,
        ]

    def test_before_and_after_share_one_session_id(self) -> None:
        layer = FakeLayer()
        checkpoints = [
            PolicyCheckpoint(EventType.INPUT_RECEIVED, before_node_execution=True),
            PolicyCheckpoint(EventType.OUTPUT_PRE_SEND, before_node_execution=False),
        ]
        # No thread_id: the two checkpoints of this one node execution must still
        # share a session id (the bug minted a fresh UUID per checkpoint).
        NodeWrapper(layer, checkpoints).wrap("n", lambda s: s)({"x": 1})
        session_ids = {c.metadata.session_id for c in layer.calls}
        assert len(session_ids) == 1

    def test_deny_before_aborts_node(self) -> None:
        layer = FakeLayer(Verdict.deny(reasoning="no"))
        ran: list[int] = []

        def node(state: Any) -> Any:
            ran.append(1)
            return state

        wrapped = NodeWrapper(
            layer,
            [PolicyCheckpoint(EventType.INPUT_RECEIVED, before_node_execution=True)],
        ).wrap("n", node)

        with pytest.raises(PolicyDenied):
            wrapped({"x": 1})
        assert ran == []  # node body never executed

    async def test_async_node_is_wrapped(self) -> None:
        layer = FakeLayer()

        async def node(state: Any) -> Any:
            return {"v": 2}

        wrapped = NodeWrapper(
            layer,
            [PolicyCheckpoint(EventType.INPUT_RECEIVED, before_node_execution=True)],
        ).wrap("n", node)

        assert await wrapped({"v": 0}) == {"v": 2}
        assert len(layer.calls) == 1

    def test_config_is_passed_to_node(self) -> None:
        layer = FakeLayer()
        seen: dict[str, Any] = {}

        def node(state: Any, config: Any = None) -> Any:
            seen["config"] = config
            return state

        config = {"configurable": {"thread_id": "T"}}
        NodeWrapper(layer, []).wrap("n", node)({"x": 1}, config)
        assert seen["config"] == config

    def test_modify_before_checkpoint_changes_what_node_sees(self) -> None:
        # A MODIFY in a before-checkpoint must mutate the state the node receives.
        layer = FakeLayer(
            Verdict.modify(target="tool_args", operation="replace", value={"safe": 1})
        )
        seen: dict[str, Any] = {}

        def node(state: Any) -> Any:
            seen["tool_args"] = state.get("tool_args")
            return state

        NodeWrapper(
            layer,
            [PolicyCheckpoint(EventType.TOOL_PRE_INVOKE, before_node_execution=True)],
        ).wrap("n", node)({"tool_args": {"danger": 1}})
        assert seen["tool_args"] == {"safe": 1}

    def test_non_callable_non_spec_raises(self) -> None:
        with pytest.raises(TypeError, match="Cannot wrap node"):
            NodeWrapper(FakeLayer(), []).wrap("n", 12345)

    def test_wrap_handles_uninspectable_callable(self) -> None:
        # A C builtin with no introspectable signature (range) must not crash
        # wrap(); _accepts_config falls back to "no config param".
        wrapped = NodeWrapper(FakeLayer(), []).wrap("n", range)
        assert callable(wrapped)


class _FakeGraph:
    """
    Duck-typed StateGraph stand-in (callable nodes, no langgraph dep).
    """

    def __init__(self) -> None:
        self.nodes: dict[str, Any] = {}

    def add_node(self, name: str, func: Any) -> None:
        self.nodes[name] = func

    def add_edge(self, *_args: Any) -> None:  # pragma: no cover - unused here
        pass


class TestCreateAplGraphFactory:
    def test_wraps_each_node(self) -> None:
        graph = _FakeGraph()

        def original(state: Any) -> Any:
            return state

        graph.add_node("n", original)

        wrapped = create_apl_graph(graph, policy_servers=["stdio://noop.py"])

        assert wrapped is graph
        # The node was replaced by a policy-enforcing wrapper, not left as-is.
        assert graph.nodes["n"] is not original
        assert callable(graph.nodes["n"])


class TestAPLGraphWrapper:
    def test_subclasses_base_framework_adapter(self) -> None:
        assert issubclass(APLGraphWrapper, BaseFrameworkAdapter)

    def test_framework_name(self) -> None:
        assert APLGraphWrapper().framework_name == "langgraph"

    def test_is_available_returns_bool(self) -> None:
        assert isinstance(APLGraphWrapper.is_available(), bool)

    def test_wrap_non_graph_raises_typed_error(self) -> None:
        # Loud and typed, not a silent no-op (the old _wrap_langgraph stub).
        with pytest.raises(TypeError, match="StateGraph"):
            APLGraphWrapper().wrap(object())

    def test_add_server_is_fluent(self) -> None:
        wrapper = APLGraphWrapper()
        assert wrapper.add_server("stdio://x") is wrapper

    def test_add_checkpoint_records_checkpoint(self) -> None:
        wrapper = APLGraphWrapper().add_checkpoint(
            "tool.pre_invoke", node_name="t", before=True
        )
        assert wrapper._checkpoints[0].event_type == EventType.TOOL_PRE_INVOKE
        assert wrapper._checkpoints[0].node_name == "t"


# =============================================================================
# Integration: real LangGraph StateGraph (gated on the optional extra)
# =============================================================================


def _recording_server(records: Optional[list] = None):
    """
    A PolicyServer whose policies allow but record each event's session id.
    """
    from apl import PolicyServer, Verdict

    sink = records if records is not None else []
    server = PolicyServer("session-it")

    def _register(event_name: str) -> None:
        @server.policy(name=f"record-{event_name}", events=[event_name])
        async def _record(event):
            sink.append(event.metadata.session_id)
            return Verdict.allow()

    for event_name in ("input.received", "tool.pre_invoke", "output.pre_send"):
        _register(event_name)
    return server


def _blocking_server():
    """
    A PolicyServer that denies any output containing 'SECRET'.
    """
    from apl import PolicyServer, Verdict

    server = PolicyServer("adapter-it")

    @server.policy(
        name="block-secret",
        events=["output.pre_send"],
        context=["payload.output_text"],
    )
    async def block_secret(event):
        if "SECRET" in (event.payload.output_text or ""):
            return Verdict.deny(reasoning="secret leaked")
        return Verdict.allow()

    return server


def _redacting_server():
    """
    A PolicyServer that redacts any output containing 'SECRET' via MODIFY.
    """
    from apl import PolicyServer, Verdict

    server = PolicyServer("redact-it")

    @server.policy(
        name="redact-secret",
        events=["output.pre_send"],
        context=["payload.output_text"],
    )
    async def redact_secret(event):
        if "SECRET" in (event.payload.output_text or ""):
            return Verdict.modify(
                target="output",
                operation="replace",
                value="[REDACTED]",
                reasoning="redacted secret",
            )
        return Verdict.allow()

    return server


def _layer_with_inprocess_server(server):
    """
    Real ``PolicyLayer`` driving ``server`` in-process.

    Injecting an in-process client (a test seam) exercises the real event-building and
    verdict composition without spinning up a network transport, which is what we want
    to verify in the adapter.
    """
    from apl.layer import PolicyLayer

    class _InProcessClient:
        async def connect(self) -> None: ...

        async def close(self) -> None: ...

        @property
        def manifest(self):
            return None

        async def evaluate(self, event):
            return await server.evaluate(event)

    layer = PolicyLayer()
    layer._clients = [_InProcessClient()]
    layer._is_connected = True
    return layer


def _two_node_app(layer):
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class State(TypedDict):
        value: int
        output: str

    def safe(state: State) -> dict:
        return {"value": state.get("value", 0) + 1}

    def leak(state: State) -> dict:
        return {"output": "SECRET data"}

    graph = StateGraph(State)
    graph.add_node("safe", safe)
    graph.add_node("leak", leak)
    graph.add_edge(START, "safe")
    graph.add_edge("safe", "leak")
    graph.add_edge("leak", END)
    return APLGraphWrapper(layer).wrap(graph).compile()


@requires_langgraph
class TestLangGraphIntegration:
    def test_is_available_true_when_installed(self) -> None:
        assert APLGraphWrapper.is_available() is True

    def test_policy_fires_on_node_sync(self) -> None:
        app = _two_node_app(_layer_with_inprocess_server(_blocking_server()))
        with pytest.raises(PolicyDenied) as exc_info:
            app.invoke({"value": 0, "output": ""})
        assert "secret" in exc_info.value.verdict.reasoning.lower()

    async def test_policy_fires_when_invoked_from_running_loop(self) -> None:
        app = _two_node_app(_layer_with_inprocess_server(_blocking_server()))
        with pytest.raises(PolicyDenied):
            await app.ainvoke({"value": 0, "output": ""})

    def test_safe_graph_passes_through(self) -> None:
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph

        class State(TypedDict):
            value: int
            output: str

        def safe(state: State) -> dict:
            return {"value": state.get("value", 0) + 1, "output": "fine"}

        graph = StateGraph(State)
        graph.add_node("safe", safe)
        graph.add_edge(START, "safe")
        graph.add_edge("safe", END)
        app = (
            APLGraphWrapper(_layer_with_inprocess_server(_blocking_server()))
            .wrap(graph)
            .compile()
        )

        assert app.invoke({"value": 0, "output": ""})["value"] == 1

    def test_session_id_is_thread_id_across_all_checkpoints(self) -> None:
        captured: list[str] = []
        app = _two_node_app(_layer_with_inprocess_server(_recording_server(captured)))

        app.invoke(
            {"value": 0, "output": ""},
            {"configurable": {"thread_id": "THREAD-9"}},
        )

        assert captured  # checkpoints actually fired
        assert set(captured) == {"THREAD-9"}  # one stable session across the run

    def test_modify_redacts_node_output(self) -> None:
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph

        class State(TypedDict):
            output: str

        def leak(state: State) -> dict:
            return {"output": "SECRET data"}

        graph = StateGraph(State)
        graph.add_node("leak", leak)
        graph.add_edge(START, "leak")
        graph.add_edge("leak", END)
        app = (
            APLGraphWrapper(_layer_with_inprocess_server(_redacting_server()))
            .wrap(graph)
            .compile()
        )

        # The MODIFY verdict rewrites the node's output before it leaves the graph.
        assert app.invoke({"output": ""})["output"] == "[REDACTED]"
