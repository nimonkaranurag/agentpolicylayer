from typing import TYPE_CHECKING

from apl.logging import get_logger
from apl.types import EventType, PolicyEvent, Verdict

from .handler_invoker import invoke_policy_handler

if TYPE_CHECKING:
    from .registered_policy import RegisteredPolicy

logger = get_logger("server")


class PolicyRegistry:
    def __init__(self):
        self._policies: dict[str, "RegisteredPolicy"] = {}
        self._handlers_by_event: dict[EventType, list["RegisteredPolicy"]] = {}

    def register(self, policy: "RegisteredPolicy") -> None:
        self._policies[policy.name] = policy

        for event_type in policy.events:
            if event_type not in self._handlers_by_event:
                self._handlers_by_event[event_type] = []
            self._handlers_by_event[event_type].append(policy)

        logger.info(
            f"Registered policy: {policy.name} for events: "
            f"{[e.value for e in policy.events]}"
        )

    def get_policy_by_name(self, name: str) -> "RegisteredPolicy | None":
        return self._policies.get(name)

    def get_handlers_for_event_type(
        self, event_type: EventType
    ) -> list["RegisteredPolicy"]:
        return self._handlers_by_event.get(event_type, [])

    def all_policies(self) -> list["RegisteredPolicy"]:
        return list(self._policies.values())

    async def evaluate_event(self, event: PolicyEvent) -> list[Verdict]:
        handlers = self.get_handlers_for_event_type(event.type)

        if not handlers:
            return [Verdict.allow(reasoning="No policies registered for this event")]

        verdicts = []
        for policy in handlers:
            verdict = await invoke_policy_handler(policy, event)
            verdicts.append(verdict)

        return verdicts
