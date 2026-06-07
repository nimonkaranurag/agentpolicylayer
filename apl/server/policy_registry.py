from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Optional

from apl.logging import get_logger
from apl.modifications import apply_operation
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
        self._policies: dict[str, RegisteredPolicy] = {}
        self._handlers_by_event: dict[EventType, list[RegisteredPolicy]] = {}

    def register(self, policy: RegisteredPolicy) -> None:
        self._policies[policy.name] = policy

        for event_type in policy.events:
            if event_type not in self._handlers_by_event:
                self._handlers_by_event[event_type] = []
            self._handlers_by_event[event_type].append(policy)

        logger.info(
            f"Registered policy: {policy.name} for events: "
            f"{[e.value for e in policy.events]}"
        )

    def get_policy_by_name(self, name: str) -> RegisteredPolicy | None:
        return self._policies.get(name)

    def get_handlers_for_event_type(
        self, event_type: EventType
    ) -> list[RegisteredPolicy]:
        return self._handlers_by_event.get(event_type, [])

    def all_policies(self) -> list[RegisteredPolicy]:
        return list(self._policies.values())

    async def evaluate_event(self, event: PolicyEvent) -> list[Verdict]:
        handlers = self.get_handlers_for_event_type(event.type)

        if not handlers:
            return [Verdict.allow(reasoning="No policies registered for this event")]

        verdicts: list[Verdict] = []
        current_event = event

        for policy in handlers:
            verdict = await invoke_policy_handler(policy, current_event)
            verdicts.append(verdict)

            if verdict.decision == Decision.MODIFY:
                for modification in verdict.modifications:
                    current_event = self._apply_modification(
                        current_event, modification
                    )

        return verdicts

    def _apply_modification(
        self,
        event: PolicyEvent,
        modification: Modification,
    ) -> PolicyEvent:
        """
        Apply one modification to the event's payload during sequential evaluation.

        The modification's ``operation`` (replace/redact/append/prepend/patch) is
        honoured via the shared dispatcher; the payload is rebuilt with
        :func:`dataclasses.replace`, so untouched fields are preserved and the original
        event is never mutated.
        """
        field_name = self._payload_field_for_target(event.payload, modification.target)
        if field_name is None:
            return event

        current = getattr(event.payload, field_name)
        new_value = apply_operation(current, modification)
        new_payload = dataclasses.replace(event.payload, **{field_name: new_value})
        return dataclasses.replace(event, payload=new_payload)

    @staticmethod
    def _payload_field_for_target(payload: EventPayload, target: str) -> Optional[str]:
        """
        Map a modification ``target`` to the payload field it writes, or ``None`` if the
        server-side sequential path cannot modify it.

        Message-valued targets (``input``) live on the event, not the payload, so they
        can only be modified by the in-process instrumentation events.
        """
        if target == "output":
            return "tool_result" if payload.tool_result is not None else "output_text"
        if target == "tool_args":
            return "tool_args"
        if target == "llm_prompt":
            return "llm_prompt"

        logger.warning(
            f"Modification target {target!r} is not supported during sequential "
            f"evaluation; use instrumentation-level events instead"
        )
        return None
