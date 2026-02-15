from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apl.types import Verdict


class PolicyDenied(Exception):

    def __init__(self, verdict: Verdict) -> None:
        self.verdict: Verdict = verdict
        super().__init__(
            verdict.reasoning or "Policy denied"
        )


class PolicyEscalation(Exception):

    def __init__(self, verdict: Verdict) -> None:
        self.verdict: Verdict = verdict
        escalation_prompt: str = (
            verdict.escalation.prompt
            if verdict.escalation
            else "Escalation required"
        )
        super().__init__(escalation_prompt)
