from __future__ import annotations

import asyncio

import pytest

from apl.server import PolicyServer
from apl.server.handler_invoker import (
    invoke_policy_handler,
)
from apl.server.manifest_generator import (
    generate_manifest_from_server,
)
from apl.server.policy_registry import PolicyRegistry
from apl.server.registered_policy import (
    RegisteredPolicy,
)
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    PolicyEvent,
    Verdict,
)


class TestPolicyServer:

    def test_create_server(self):
        server = PolicyServer(
            "test-server",
            version="2.0.0",
            description="a test",
        )
        assert server.name == "test-server"
        assert server.version == "2.0.0"
        assert server.description == "a test"

    def test_decorator_registers_policy(self):
        server = PolicyServer("test")

        @server.policy(
            name="my-policy",
            events=["output.pre_send"],
        )
        async def my_policy(event):
            return Verdict.allow()

        policies = server.registry.all_policies()
        assert len(policies) == 1
        assert policies[0].name == "my-policy"
        assert (
            EventType.OUTPUT_PRE_SEND
            in policies[0].events
        )

    def test_decorator_with_full_options(self):
        server = PolicyServer("test")

        @server.policy(
            name="full",
            events=[
                "input.received",
                "output.pre_send",
            ],
            context=["metadata.user_id"],
            version="2.0",
            blocking=False,
            timeout_ms=500,
            description="full opts",
        )
        async def handler(event):
            return Verdict.allow()

        p = server.registry.get_policy_by_name("full")
        assert p is not None
        assert p.version == "2.0"
        assert p.blocking is False
        assert p.timeout_ms == 500
        assert p.description == "full opts"
        assert len(p.events) == 2

    def test_multiple_policies(self):
        server = PolicyServer("multi")

        @server.policy(
            name="p1", events=["input.received"]
        )
        async def p1(event):
            return Verdict.allow()

        @server.policy(
            name="p2", events=["output.pre_send"]
        )
        async def p2(event):
            return Verdict.deny("no")

        assert len(server.registry.all_policies()) == 2

    @pytest.mark.asyncio
    async def test_evaluate_routes_to_correct_handlers(
        self, make_event
    ):
        server = PolicyServer("test")

        @server.policy(
            name="output-guard",
            events=["output.pre_send"],
        )
        async def guard(event):
            return Verdict.deny("blocked")

        @server.policy(
            name="input-logger",
            events=["input.received"],
        )
        async def logger(event):
            return Verdict.observe()

        event = make_event(
            event_type=EventType.OUTPUT_PRE_SEND
        )
        verdicts = await server.evaluate(event)
        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.DENY

    @pytest.mark.asyncio
    async def test_evaluate_no_handlers_returns_allow(
        self, make_event
    ):
        server = PolicyServer("empty")
        event = make_event(
            event_type=EventType.INPUT_RECEIVED
        )
        verdicts = await server.evaluate(event)
        assert len(verdicts) == 1
        assert verdicts[0].decision == Decision.ALLOW

    def test_manifest_generation(self):
        server = PolicyServer(
            "manifest-test",
            version="1.5.0",
            description="desc",
        )

        @server.policy(
            name="p1",
            events=["output.pre_send"],
            version="2.0",
        )
        async def p1(event):
            return Verdict.allow()

        manifest = server.get_manifest()
        assert manifest.server_name == "manifest-test"
        assert manifest.server_version == "1.5.0"
        assert manifest.description == "desc"
        assert len(manifest.policies) == 1
        assert manifest.policies[0].name == "p1"
        assert manifest.policies[0].version == "2.0"


class TestPolicyRegistry:

    def _make_registered_policy(
        self, name="test", events=None
    ):
        return RegisteredPolicy(
            name=name,
            version="1.0",
            handler=lambda e: Verdict.allow(),
            events=events
            or [EventType.OUTPUT_PRE_SEND],
            context_requirements=[],
            blocking=True,
            timeout_ms=1000,
        )

    def test_register_and_retrieve(self):
        reg = PolicyRegistry()
        policy = self._make_registered_policy(
            "my-policy"
        )
        reg.register(policy)
        assert (
            reg.get_policy_by_name("my-policy")
            is policy
        )

    def test_get_nonexistent_returns_none(self):
        reg = PolicyRegistry()
        assert reg.get_policy_by_name("nope") is None

    def test_handlers_by_event(self):
        reg = PolicyRegistry()
        reg.register(
            self._make_registered_policy(
                "p1", [EventType.OUTPUT_PRE_SEND]
            )
        )
        reg.register(
            self._make_registered_policy(
                "p2", [EventType.OUTPUT_PRE_SEND]
            )
        )
        reg.register(
            self._make_registered_policy(
                "p3", [EventType.INPUT_RECEIVED]
            )
        )

        output_handlers = (
            reg.get_handlers_for_event_type(
                EventType.OUTPUT_PRE_SEND
            )
        )
        assert len(output_handlers) == 2

        input_handlers = (
            reg.get_handlers_for_event_type(
                EventType.INPUT_RECEIVED
            )
        )
        assert len(input_handlers) == 1

    def test_no_handlers_returns_empty(self):
        reg = PolicyRegistry()
        assert (
            reg.get_handlers_for_event_type(
                EventType.SESSION_START
            )
            == []
        )


class TestHandlerInvoker:

    @pytest.mark.asyncio
    async def test_async_handler(self, make_event):
        async def handler(event):
            return Verdict.deny("async deny")

        policy = RegisteredPolicy(
            name="async-test",
            version="1.0",
            handler=handler,
            events=[EventType.OUTPUT_PRE_SEND],
            context_requirements=[],
            blocking=True,
            timeout_ms=5000,
        )
        event = make_event()
        result = await invoke_policy_handler(
            policy, event
        )
        assert result.decision == Decision.DENY
        assert result.policy_name == "async-test"
        assert result.evaluation_ms is not None

    @pytest.mark.asyncio
    async def test_sync_handler(self, make_event):
        def handler(event):
            return Verdict.allow(reasoning="sync ok")

        policy = RegisteredPolicy(
            name="sync-test",
            version="1.0",
            handler=handler,
            events=[EventType.OUTPUT_PRE_SEND],
            context_requirements=[],
            blocking=True,
            timeout_ms=5000,
        )
        event = make_event()
        result = await invoke_policy_handler(
            policy, event
        )
        assert result.decision == Decision.ALLOW
        assert result.policy_name == "sync-test"

    @pytest.mark.asyncio
    async def test_handler_exception_returns_allow(
        self, make_event
    ):
        async def handler(event):
            raise RuntimeError("boom")

        policy = RegisteredPolicy(
            name="crash",
            version="1.0",
            handler=handler,
            events=[EventType.OUTPUT_PRE_SEND],
            context_requirements=[],
            blocking=True,
            timeout_ms=5000,
        )
        event = make_event()
        result = await invoke_policy_handler(
            policy, event
        )
        assert result.decision == Decision.ALLOW
        assert "error" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_handler_non_verdict_returns_allow(
        self, make_event
    ):
        async def handler(event):
            return "not a verdict"

        policy = RegisteredPolicy(
            name="bad-return",
            version="1.0",
            handler=handler,
            events=[EventType.OUTPUT_PRE_SEND],
            context_requirements=[],
            blocking=True,
            timeout_ms=5000,
        )
        event = make_event()
        result = await invoke_policy_handler(
            policy, event
        )
        assert result.decision == Decision.ALLOW
