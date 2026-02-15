from apl.types import Decision, Verdict


class FirstApplicableStrategy:
    def compose(self, verdicts: list[Verdict]) -> Verdict:
        if not verdicts:
            return Verdict.allow(reasoning="No policies evaluated")

        for verdict in verdicts:
            if verdict.decision != Decision.OBSERVE:
                return verdict

        return Verdict.allow(reasoning="No applicable policy")
