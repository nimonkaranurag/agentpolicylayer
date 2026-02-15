from apl.types import Decision, Verdict


class WeightedStrategy:
    def compose(self, verdicts: list[Verdict]) -> Verdict:
        if not verdicts:
            return Verdict.allow(
                reasoning="No policies evaluated"
            )

        allow_score = sum(
            v.confidence
            for v in verdicts
            if v.decision == Decision.ALLOW
        )
        deny_score = sum(
            v.confidence
            for v in verdicts
            if v.decision == Decision.DENY
        )

        if deny_score > allow_score:
            denies = [
                v
                for v in verdicts
                if v.decision == Decision.DENY
            ]
            if denies:
                return denies[0]
            return Verdict.deny(
                reasoning=f"Weighted deny ({deny_score:.2f} vs {allow_score:.2f})"
            )

        return Verdict.allow(
            reasoning=f"Weighted allow ({allow_score:.2f} vs {deny_score:.2f})"
        )
