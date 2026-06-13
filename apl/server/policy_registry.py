from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from apl.logging import get_logger
from apl.modifications import (
    UnsupportedModificationTarget,
    apply_modifications,
)
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


class DuplicatePolicyError(ValueError):
    """
    Raised when two policies are registered under the same name.

    Silently keeping only the last of two same-named policies would drop an author's
    policy without warning — a fail-open hazard for a guardrails product — so
    registration rejects the duplicate instead.
    """


class PolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, RegisteredPolicy] = {}
        self._handlers_by_event: dict[EventType, list[RegisteredPolicy]] = {}

    def register(self, policy: RegisteredPolicy) -> None:
        if policy.name in self._policies:
            raise DuplicatePolicyError(
                f"Duplicate policy name {policy.name!r}: policy names must be "
                f"unique within a server"
            )
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

        # No handler for this event type means this server has *no opinion* — it
        # must abstain (empty verdict list), not vote. A full-confidence ALLOW here
        # crosses the wire as a real verdict and, under allow_overrides / weighted /
        # first_applicable, out-votes a genuine deny from another server. Every
        # composition strategy already treats an empty list as neutral.
        if not handlers:
            return []

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

        Routed through the shared :func:`apply_modifications`, so ``operation``
        (replace/redact/append/prepend/patch) means the same here as at every other
        enforcement point; the payload is rebuilt with
        :meth:`~pydantic.BaseModel.model_copy`, so untouched fields are preserved and
        the original event is never mutated.

        A target the server-side payload can't represent (e.g. ``input``/``plan``)
        raises :class:`UnsupportedModificationTarget`, which we catch and skip *for the
        sequential pre-application only* — the modification is still returned in the
        policy's verdict and enforced fail-closed at the instrumentation layer, so
        chaining it here is best-effort, not a missed enforcement.
        """
        holder: dict[str, PolicyEvent] = {"event": event}

        def resolve(target: str):
            field_name = self._payload_field_for_target(holder["event"].payload, target)
            if field_name is None:
                return None

            def read_current() -> Any:
                return getattr(holder["event"].payload, field_name)

            def write_new(value: Any) -> None:
                new_payload = holder["event"].payload.model_copy(
                    update={field_name: value}
                )
                holder["event"] = holder["event"].model_copy(
                    update={"payload": new_payload}
                )

            return read_current, write_new

        try:
            apply_modifications([modification], resolve)
        except UnsupportedModificationTarget:
            logger.debug(
                f"Modification target {modification.target!r} is not chainable "
                f"during sequential evaluation; it is still returned in the verdict "
                f"and enforced at the instrumentation layer."
            )
        return holder["event"]

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
        return None
