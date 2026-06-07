from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone

import pytest

from apl.types import (
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    SessionMetadata,
)

# Lets tests use the ``pytester`` fixture (e.g. to verify the async-execution
# guard below); ``pytest_plugins`` is only honoured in the top-level conftest.
pytest_plugins = ["pytester"]


def async_execution_error(
    asyncio_plugin_active: bool,
    async_node_ids: list[str],
) -> str | None:
    """
    Return a failure message if collected async tests cannot execute, else None.

    This is the pure decision behind :func:`pytest_collection_modifyitems`, factored out
    so the collected-async == executed-async invariant (WP-11, ENGINEERING_REVIEW §6) is
    unit-testable without spawning a subprocess.

    Without an active async plugin, pytest cannot await ``async def`` tests;
    historically they were reported as passing no-ops, silently hiding the entire
    server/integration path. If any async test is collected while the ``asyncio`` plugin
    is inactive, refuse the run rather than pass vacuously.
    """
    if asyncio_plugin_active or not async_node_ids:
        return None
    shown = ", ".join(async_node_ids[:3])
    suffix = "..." if len(async_node_ids) > 3 else ""
    return (
        f"{len(async_node_ids)} async test(s) were collected but the pytest "
        "'asyncio' plugin is not active, so they would not execute (and would "
        "silently count as passing). Install the 'dev' extra (pytest-asyncio) "
        f"and keep asyncio_mode=auto. Affected: {shown}{suffix}"
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """
    Fail the session loudly if async tests were collected but can't run.

    Guards the collected-async == executed-async invariant so a missing or disabled
    pytest-asyncio can never again hide an untested async subsystem.
    """
    async_node_ids = [
        item.nodeid
        for item in items
        if inspect.iscoroutinefunction(getattr(item, "obj", None))
    ]
    message = async_execution_error(
        config.pluginmanager.hasplugin("asyncio"),
        async_node_ids,
    )
    if message is not None:
        raise pytest.UsageError(message)


@pytest.fixture
def sample_messages() -> list[Message]:
    return [
        Message(
            role="system",
            content="You are a helpful assistant.",
        ),
        Message(
            role="user",
            content="What is the capital of France?",
        ),
        Message(
            role="assistant",
            content="The capital of France is Paris.",
        ),
    ]


@pytest.fixture
def sample_metadata() -> SessionMetadata:
    return SessionMetadata(
        session_id="test-session-001",
        user_id="user-42",
        agent_id="agent-alpha",
        user_roles=["admin"],
        user_region="EU",
    )


@pytest.fixture
def sample_payload() -> EventPayload:
    return EventPayload(output_text="Hello, world!")


@pytest.fixture
def sample_tool_payload() -> EventPayload:
    return EventPayload(
        tool_name="web_search",
        tool_args={"query": "latest news"},
    )


@pytest.fixture
def sample_llm_payload(
    sample_messages: list[Message],
) -> EventPayload:
    return EventPayload(
        llm_model="gpt-4",
        llm_prompt=sample_messages,
    )


@pytest.fixture
def sample_event(
    sample_messages: list[Message],
    sample_metadata: SessionMetadata,
    sample_payload: EventPayload,
) -> PolicyEvent:
    return PolicyEvent(
        id=str(uuid.uuid4()),
        type=EventType.OUTPUT_PRE_SEND,
        timestamp=datetime.now(timezone.utc),
        messages=sample_messages,
        payload=sample_payload,
        metadata=sample_metadata,
    )


@pytest.fixture
def make_event():
    def _factory(
        event_type: EventType = EventType.OUTPUT_PRE_SEND,
        messages: list[Message] | None = None,
        payload: EventPayload | None = None,
        metadata: SessionMetadata | None = None,
    ) -> PolicyEvent:
        return PolicyEvent(
            id=str(uuid.uuid4()),
            type=event_type,
            timestamp=datetime.now(timezone.utc),
            messages=messages or [],
            payload=payload or EventPayload(),
            metadata=metadata or SessionMetadata(session_id="test"),
        )

    return _factory
