from apl.types import Decision, Verdict


class AllowOverridesStrategy:
    def compose(self, verdicts: list[Verdict]) -> Verdict:
        if not verdicts:
            return Verdict.deny(reasoning="No policies evaluated")

        for verdict in verdicts:
            if verdict.decision == Decision.ALLOW:
                return verdict

        for verdict in verdicts:
            if verdict.decision == Decision.MODIFY:
                return verdict

        for verdict in verdicts:
            if verdict.decision == Decision.ESCALATE:
                return verdict

        denies = [v for v in verdicts if v.decision == Decision.DENY]
        if denies:
            return denies[0]

        return Verdict.deny(reasoning="No policy allowed")
