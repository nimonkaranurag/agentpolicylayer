from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    SessionMetadata,
    Verdict,
)


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
            metadata=metadata
            or SessionMetadata(session_id="test"),
        )

    return _factory
