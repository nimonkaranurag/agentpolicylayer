from apl.layer import PolicyDenied, PolicyEscalation
from apl.logging import get_logger
from apl.types import Decision, Verdict

logger = get_logger("instrumentation.verdict_handler")


class VerdictHandler:
    def raise_if_blocked(
        self, verdict: Verdict, event_name: str
    ) -> None:
        if verdict.decision == Decision.DENY:
            logger.warning(
                f"Policy denied at {event_name}: {verdict.reasoning}"
            )
            raise PolicyDenied(verdict)

        if verdict.decision == Decision.ESCALATE:
            logger.info(
                f"Policy escalation at {event_name}: {verdict.reasoning}"
            )
            raise PolicyEscalation(verdict)
