from apl.types import Decision, Verdict


class UnanimousStrategy:
    def compose(self, verdicts: list[Verdict]) -> Verdict:
        if not verdicts:
            return Verdict.allow(
                reasoning="No policies evaluated"
            )

        for verdict in verdicts:
            if verdict.decision == Decision.DENY:
                return verdict

        for verdict in verdicts:
            if verdict.decision == Decision.ESCALATE:
                return verdict

        for verdict in verdicts:
            if verdict.decision == Decision.MODIFY:
                return verdict

        return Verdict.allow(
            reasoning="All policies agreed"
        )
