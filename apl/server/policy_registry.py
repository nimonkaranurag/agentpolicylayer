from __future__ import annotations

from typing import TYPE_CHECKING

from apl.logging import get_logger
from apl.types import (
    Decision,
    EventPayload,
    EventType,
    Modification,
    PolicyEvent,
    Verdict,
)

from .handler_invoker import invoke_policy_handler

if TYPE_CHECKING:
    from .registered_policy import RegisteredPolicy

logger = get_logger("server")


class PolicyRegistry:

    def __init__(self) -> None:
        self._policies: dict[str, RegisteredPolicy] = (
            {}
        )
        self._handlers_by_event: dict[
            EventType, list[RegisteredPolicy]
        ] = {}

    def register(
        self, policy: RegisteredPolicy
    ) -> None:
        self._policies[policy.name] = policy

        for event_type in policy.events:
            if (
                event_type
                not in self._handlers_by_event
            ):
                self._handlers_by_event[event_type] = (
                    []
                )
            self._handlers_by_event[event_type].append(
                policy
            )

        logger.info(
            f"Registered policy: {policy.name} for events: "
            f"{[e.value for e in policy.events]}"
        )

    def get_policy_by_name(
        self, name: str
    ) -> RegisteredPolicy | None:
        return self._policies.get(name)

    def get_handlers_for_event_type(
        self, event_type: EventType
    ) -> list[RegisteredPolicy]:
        return self._handlers_by_event.get(
            event_type, []
        )

    def all_policies(self) -> list[RegisteredPolicy]:
        return list(self._policies.values())

    async def evaluate_event(
        self, event: PolicyEvent
    ) -> list[Verdict]:
        handlers = self.get_handlers_for_event_type(
            event.type
        )

        if not handlers:
            return [
                Verdict.allow(
                    reasoning="No policies registered for this event"
                )
            ]

        verdicts: list[Verdict] = []
        current_event = event

        for policy in handlers:
            verdict = await invoke_policy_handler(
                policy, current_event
            )
            verdicts.append(verdict)

            if verdict.decision == Decision.MODIFY:
                for (
                    modification
                ) in verdict.modifications:
                    current_event = (
                        self._apply_modification(
                            current_event, modification
                        )
                    )

        return verdicts

    def _apply_modification(
        self,
        event: PolicyEvent,
        modification: Modification,
    ) -> PolicyEvent:
        payload = event.payload
        new_payload_kwargs = {
            "tool_name": payload.tool_name,
            "tool_args": payload.tool_args,
            "tool_result": payload.tool_result,
            "tool_error": payload.tool_error,
            "llm_model": payload.llm_model,
            "llm_prompt": payload.llm_prompt,
            "llm_response": payload.llm_response,
            "llm_tokens_used": payload.llm_tokens_used,
            "output_text": payload.output_text,
            "output_structured": payload.output_structured,
            "plan": payload.plan,
            "target_agent": payload.target_agent,
            "source_agent": payload.source_agent,
            "handoff_payload": payload.handoff_payload,
        }

        target = modification.target
        value = modification.value

        if target == "output":
            if payload.tool_result is not None:
                new_payload_kwargs["tool_result"] = (
                    value
                )
            elif payload.output_text is not None:
                new_payload_kwargs["output_text"] = (
                    value
                )
            else:
                new_payload_kwargs["output_text"] = (
                    value
                )
        elif target == "input":
            logger.warning(
                f"Modification target 'input' is not supported during sequential evaluation; "
                f"use instrumentation-level events for input modifications"
            )
        elif target == "tool_args":
            new_payload_kwargs["tool_args"] = value
        elif target == "llm_prompt":
            new_payload_kwargs["llm_prompt"] = value

        new_payload = EventPayload(
            **new_payload_kwargs
        )

        return PolicyEvent(
            id=event.id,
            type=event.type,
            timestamp=event.timestamp,
            messages=event.messages,
            payload=new_payload,
            metadata=event.metadata,
        )
