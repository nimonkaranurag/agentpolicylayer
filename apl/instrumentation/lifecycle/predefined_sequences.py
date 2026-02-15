from ..events import get_event
from .sequence import EventSequence

LLM_CALL_PRE_REQUEST_SEQUENCE = EventSequence(
    name="llm_call_pre_request",
    events=[
        get_event("input.received"),
        get_event("llm.pre_request"),
    ],
)

LLM_CALL_POST_RESPONSE_SEQUENCE = EventSequence(
    name="llm_call_post_response",
    events=[
        get_event("llm.post_response"),
        get_event("output.pre_send"),
    ],
)

TOOL_CALL_PRE_INVOKE_SEQUENCE = EventSequence(
    name="tool_call_pre_invoke",
    events=[
        get_event("tool.pre_invoke"),
    ],
)

TOOL_CALL_POST_INVOKE_SEQUENCE = EventSequence(
    name="tool_call_post_invoke",
    events=[
        get_event("tool.post_invoke"),
    ],
)

AGENT_HANDOFF_PRE_SEQUENCE = EventSequence(
    name="agent_handoff_pre",
    events=[
        get_event("agent.pre_handoff"),
    ],
)

AGENT_HANDOFF_POST_SEQUENCE = EventSequence(
    name="agent_handoff_post",
    events=[
        get_event("agent.post_handoff"),
    ],
)

SESSION_START_SEQUENCE = EventSequence(
    name="session_start",
    events=[
        get_event("session.start"),
    ],
)

SESSION_END_SEQUENCE = EventSequence(
    name="session_end",
    events=[
        get_event("session.end"),
    ],
)
