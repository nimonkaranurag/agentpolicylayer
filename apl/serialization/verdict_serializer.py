from typing import Any

from apl.types import Decision, Escalation, Modification, Verdict


class VerdictSerializer:
    def serialize(self, verdict: Verdict) -> dict[str, Any]:
        result = {
            "decision": verdict.decision.value,
            "confidence": verdict.confidence,
        }

        if verdict.reasoning is not None:
            result["reasoning"] = verdict.reasoning
        if verdict.policy_name is not None:
            result["policy_name"] = verdict.policy_name
        if verdict.policy_version is not None:
            result["policy_version"] = verdict.policy_version
        if verdict.evaluation_ms is not None:
            result["evaluation_ms"] = verdict.evaluation_ms
        if verdict.trace is not None:
            result["trace"] = verdict.trace
        if verdict.modification is not None:
            result["modification"] = self._serialize_modification(verdict.modification)
        if verdict.escalation is not None:
            result["escalation"] = self._serialize_escalation(verdict.escalation)

        return result

    def deserialize(self, data: dict[str, Any]) -> Verdict:
        modification = None
        if data.get("modification"):
            modification = self._deserialize_modification(data["modification"])

        escalation = None
        if data.get("escalation"):
            escalation = self._deserialize_escalation(data["escalation"])

        return Verdict(
            decision=Decision(data["decision"]),
            confidence=data.get("confidence", 1.0),
            reasoning=data.get("reasoning"),
            modification=modification,
            escalation=escalation,
            policy_name=data.get("policy_name"),
            policy_version=data.get("policy_version"),
            evaluation_ms=data.get("evaluation_ms"),
            trace=data.get("trace"),
        )

    def _serialize_modification(self, modification: Modification) -> dict[str, Any]:
        result = {
            "target": modification.target,
            "operation": modification.operation,
            "value": modification.value,
        }
        if modification.path is not None:
            result["path"] = modification.path
        return result

    def _serialize_escalation(self, escalation: Escalation) -> dict[str, Any]:
        result = {"type": escalation.type}
        if escalation.prompt is not None:
            result["prompt"] = escalation.prompt
        if escalation.fallback_action is not None:
            result["fallback_action"] = escalation.fallback_action
        if escalation.timeout_ms is not None:
            result["timeout_ms"] = escalation.timeout_ms
        if escalation.options is not None:
            result["options"] = escalation.options
        return result

    def _deserialize_modification(self, data: dict[str, Any]) -> Modification:
        return Modification(
            target=data["target"],
            operation=data["operation"],
            value=data["value"],
            path=data.get("path"),
        )

    def _deserialize_escalation(self, data: dict[str, Any]) -> Escalation:
        return Escalation(
            type=data["type"],
            prompt=data.get("prompt"),
            fallback_action=data.get("fallback_action"),
            timeout_ms=data.get("timeout_ms"),
            options=data.get("options"),
        )
