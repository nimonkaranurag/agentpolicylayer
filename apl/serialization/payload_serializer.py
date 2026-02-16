from typing import Any

from apl.types import EventPayload


class PayloadSerializer:
    def __init__(self, message_serializer=None):
        self._message_serializer = message_serializer

    def serialize(
        self, payload: EventPayload
    ) -> dict[str, Any]:
        result = {}

        if payload.tool_name is not None:
            result["tool_name"] = payload.tool_name
        if payload.tool_args is not None:
            result["tool_args"] = payload.tool_args
        if payload.tool_result is not None:
            result["tool_result"] = payload.tool_result
        if payload.tool_error is not None:
            result["tool_error"] = payload.tool_error

        if payload.llm_model is not None:
            result["llm_model"] = payload.llm_model
        if (
            payload.llm_prompt is not None
            and self._message_serializer
        ):
            result["llm_prompt"] = [
                self._message_serializer.serialize(m)
                for m in payload.llm_prompt
            ]
        if (
            payload.llm_response is not None
            and self._message_serializer
        ):
            result["llm_response"] = (
                self._message_serializer.serialize(
                    payload.llm_response
                )
            )

        if payload.llm_tokens_used is not None:
            result["llm_tokens_used"] = (
                payload.llm_tokens_used
            )

        if payload.output_text is not None:
            result["output_text"] = payload.output_text
        if payload.output_structured is not None:
            result["output_structured"] = (
                payload.output_structured
            )

        if payload.plan is not None:
            result["plan"] = payload.plan

        if payload.target_agent is not None:
            result["target_agent"] = (
                payload.target_agent
            )
        if payload.source_agent is not None:
            result["source_agent"] = (
                payload.source_agent
            )
        if payload.handoff_payload is not None:
            result["handoff_payload"] = (
                payload.handoff_payload
            )

        return result

    def deserialize(
        self, data: dict[str, Any]
    ) -> EventPayload:
        return EventPayload(
            tool_name=data.get("tool_name"),
            tool_args=data.get("tool_args"),
            tool_result=data.get("tool_result"),
            tool_error=data.get("tool_error"),
            llm_model=data.get("llm_model"),
            llm_response=self._message_serializer.deserialize(data["llm_response"])
                if data.get("llm_response") and self._message_serializer
                else data.get("llm_response"),
            llm_tokens_used=data.get(
                "llm_tokens_used"
            ),
            output_text=data.get("output_text"),
            output_structured=data.get(
                "output_structured"
            ),
            plan=data.get("plan"),
            target_agent=data.get("target_agent"),
            source_agent=data.get("source_agent"),
            handoff_payload=data.get(
                "handoff_payload"
            ),
            llm_prompt=(
                [
                    self._message_serializer.deserialize(
                        m
                    )
                    for m in data["llm_prompt"]
                ]
                if data.get("llm_prompt")
                and self._message_serializer
                else data.get("llm_prompt")
            ),
        )
