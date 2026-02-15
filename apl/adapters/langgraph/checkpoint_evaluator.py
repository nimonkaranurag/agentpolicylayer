from typing import TYPE_CHECKING, Any

from apl.layer import PolicyDenied, PolicyEscalation
from apl.logging import get_logger
from apl.types import Decision, EventPayload, EventType, Message

from .checkpoint import PolicyCheckpoint
from .state_extractor import LangGraphStateExtractor

if TYPE_CHECKING:
    from apl.layer import PolicyLayer

logger = get_logger("adapter.langgraph")


class CheckpointEvaluator:
    
    def __init__(self, policy_layer: "PolicyLayer"):
        self._policy_layer = policy_layer
        self._state_extractor = LangGraphStateExtractor()

    async def evaluate(
        self,
        checkpoint: PolicyCheckpoint,
        state: Any,
        config: dict | None,
        node_name: str,
    ) -> None:
        messages = self._state_extractor.extract_messages(state)
        metadata = self._state_extractor.extract_metadata(state, config)
        payload = self._build_payload(checkpoint, state, node_name, messages)

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

    def _build_payload(
        self,
        checkpoint: PolicyCheckpoint,
        state: Any,
        node_name: str,
        messages: list[Message],
    ) -> EventPayload:
        payload = EventPayload()

        if checkpoint.event_type == EventType.TOOL_PRE_INVOKE:
            self._populate_tool_payload(payload, state, node_name)
        elif checkpoint.event_type == EventType.OUTPUT_PRE_SEND:
            self._populate_output_payload(payload, state, messages)

        return payload

    def _populate_tool_payload(
        self, payload: EventPayload, state: Any, node_name: str
    ) -> None:
        if isinstance(state, dict):
            payload.tool_name = state.get("tool_name") or node_name
            payload.tool_args = state.get("tool_args") or state.get("tool_input")

    def _populate_output_payload(
        self,
        payload: EventPayload,
        state: Any,
        messages: list[Message],
    ) -> None:
        if isinstance(state, dict):
            payload.output_text = state.get("output") or state.get("response")
        elif messages:
            assistant_messages = [m for m in messages if m.role == "assistant"]
            if assistant_messages:
                payload.output_text = assistant_messages[-1].content
