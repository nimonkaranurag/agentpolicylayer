import uuid
from typing import Any

from apl.types import SessionMetadata


class MetadataSerializer:
    def serialize(
        self, metadata: SessionMetadata
    ) -> dict[str, Any]:
        result = {
            "session_id": metadata.session_id,
            "token_count": metadata.token_count,
            "cost_usd": metadata.cost_usd,
            "user_roles": metadata.user_roles,
            "compliance_tags": metadata.compliance_tags,
            "started_at": metadata.started_at.isoformat(),
            "custom": metadata.custom,
        }

        if metadata.user_id is not None:
            result["user_id"] = metadata.user_id
        if metadata.agent_id is not None:
            result["agent_id"] = metadata.agent_id
        if metadata.token_budget is not None:
            result["token_budget"] = (
                metadata.token_budget
            )
        if metadata.cost_budget_usd is not None:
            result["cost_budget_usd"] = (
                metadata.cost_budget_usd
            )
        if metadata.user_region is not None:
            result["user_region"] = (
                metadata.user_region
            )

        return result

    def deserialize(
        self, data: dict[str, Any]
    ) -> SessionMetadata:
        return SessionMetadata(
            session_id=data.get(
                "session_id", str(uuid.uuid4())
            ),
            user_id=data.get("user_id"),
            agent_id=data.get("agent_id"),
            token_count=data.get("token_count", 0),
            token_budget=data.get("token_budget"),
            cost_usd=data.get("cost_usd", 0.0),
            cost_budget_usd=data.get(
                "cost_budget_usd"
            ),
            user_roles=data.get("user_roles", []),
            user_region=data.get("user_region"),
            compliance_tags=data.get(
                "compliance_tags", []
            ),
            custom=data.get("custom", {}),
        )
