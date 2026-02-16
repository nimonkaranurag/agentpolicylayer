from typing import Dict

from .agent_post_handoff_event import (
    AgentPostHandoffEvent,
)
from .agent_pre_handoff_event import (
    AgentPreHandoffEvent,
)
from .base_event import BaseEvent
from .input_received_event import InputReceivedEvent
from .input_validated_event import InputValidatedEvent
from .llm_post_response_event import (
    LLMPostResponseEvent,
)
from .llm_pre_request_event import LLMPreRequestEvent
from .output_pre_send_event import OutputPreSendEvent
from .plan_approved_event import PlanApprovedEvent
from .plan_proposed_event import PlanProposedEvent
from .session_end_event import SessionEndEvent
from .session_start_event import SessionStartEvent
from .tool_post_invoke_event import ToolPostInvokeEvent
from .tool_pre_invoke_event import ToolPreInvokeEvent

EVENT_REGISTRY: Dict[str, BaseEvent] = {
    "input.received": InputReceivedEvent(),
    "input.validated": InputValidatedEvent(),
    "llm.pre_request": LLMPreRequestEvent(),
    "llm.post_response": LLMPostResponseEvent(),
    "tool.pre_invoke": ToolPreInvokeEvent(),
    "tool.post_invoke": ToolPostInvokeEvent(),
    "output.pre_send": OutputPreSendEvent(),
    "session.start": SessionStartEvent(),
    "session.end": SessionEndEvent(),
    "plan.proposed": PlanProposedEvent(),
    "plan.approved": PlanApprovedEvent(),
    "agent.pre_handoff": AgentPreHandoffEvent(),
    "agent.post_handoff": AgentPostHandoffEvent(),
}


def get_event(event_name: str) -> BaseEvent:
    return EVENT_REGISTRY[event_name]
