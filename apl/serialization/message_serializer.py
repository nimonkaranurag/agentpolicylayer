from typing import Any

from apl.types import FunctionCall, Message, ToolCall


class MessageSerializer:
    def serialize(
        self, message: Message
    ) -> dict[str, Any]:
        result = {"role": message.role}

        if message.content is not None:
            result["content"] = message.content
        if message.name is not None:
            result["name"] = message.name
        if message.tool_call_id is not None:
            result["tool_call_id"] = (
                message.tool_call_id
            )
        if message.tool_calls is not None:
            result["tool_calls"] = [
                self._serialize_tool_call(tc)
                for tc in message.tool_calls
            ]

        return result

    def deserialize(
        self, data: dict[str, Any]
    ) -> Message:
        tool_calls = None
        if data.get("tool_calls"):
            tool_calls = [
                self._deserialize_tool_call(tc)
                for tc in data["tool_calls"]
            ]

        return Message(
            role=data["role"],
            content=data.get("content"),
            name=data.get("name"),
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
        )

    def _serialize_tool_call(
        self, tool_call: ToolCall
    ) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": tool_call.type,
            "function": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }

    def _deserialize_tool_call(
        self, data: dict[str, Any]
    ) -> ToolCall:
        return ToolCall(
            id=data["id"],
            type=data.get("type", "function"),
            function=FunctionCall(
                name=data["function"]["name"],
                arguments=data["function"][
                    "arguments"
                ],
            ),
        )
