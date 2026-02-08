"""
APL Policy Server

This is the main developer interface. Design goals:
1. ~20 lines to a working policy server
2. Decorator-based API (like Flask/FastAPI)
3. Transport-agnostic (stdio, HTTP, WebSocket)
4. Type-safe with good DX
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, Union

from .types import (
    ContextRequirement,
    Decision,
    EventType,
    PolicyDefinition,
    PolicyEvent,
    PolicyManifest,
    Verdict,
)

logger = logging.getLogger("apl")


# Type alias for policy handlers
PolicyHandler = Callable[
    [PolicyEvent], Union[Verdict, Awaitable[Verdict]]
]


@dataclass
class RegisteredPolicy:
    """Internal representation of a registered policy."""

    name: str
    version: str
    handler: PolicyHandler
    events: list[EventType]
    context_requirements: list[ContextRequirement]
    blocking: bool
    timeout_ms: int
    description: Optional[str]


class PolicyServer:
    """
    APL Policy Server.

    Usage:
        server = PolicyServer("my-policy-server")

        @server.policy(
            name="redact-pii",
            events=["output.pre_send"],
            context=["payload.output_text"]
        )
        async def redact_pii(event: PolicyEvent) -> Verdict:
            # Your policy logic here
            return Verdict.allow()

        if __name__ == "__main__":
            server.run()
    """

    def __init__(
        self,
        name: str,
        version: str = "0.1.0",
        description: str = None,
    ):
        self.name = name
        self.version = version
        self.description = description
        self._policies: dict[str, RegisteredPolicy] = {}
        self._event_handlers: dict[
            EventType, list[RegisteredPolicy]
        ] = {}

    def policy(
        self,
        name: str,
        events: list[str],
        context: list[str] = None,
        version: str = "1.0.0",
        blocking: bool = True,
        timeout_ms: int = 1000,
        description: str = None,
    ):
        """
        Decorator to register a policy handler.

        Args:
            name: Unique policy name
            events: List of event types to handle (e.g., ["tool.pre_invoke"])
            context: List of context paths needed (e.g., ["payload.tool_name"])
            version: Policy version
            blocking: Whether runtime must await this policy
            timeout_ms: Max evaluation time
            description: Human-readable description

        Example:
            @server.policy(
                name="confirm-delete",
                events=["tool.pre_invoke"],
                context=["payload.tool_name", "payload.tool_args"]
            )
            async def confirm_delete(event):
                if "delete" in event.payload.tool_name:
                    return Verdict.escalate("human_confirm", prompt="Confirm delete?")
                return Verdict.allow()
        """
        # Parse event strings to EventType enums
        event_types = []
        for e in events:
            if isinstance(e, EventType):
                event_types.append(e)
            else:
                # Handle string like "tool.pre_invoke"
                try:
                    event_types.append(EventType(e))
                except ValueError:
                    raise ValueError(
                        f"Unknown event type: {e}"
                    )

        # Parse context requirements
        context_reqs = []
        for c in context or []:
            if isinstance(c, ContextRequirement):
                context_reqs.append(c)
            else:
                context_reqs.append(
                    ContextRequirement(path=c)
                )

        def decorator(func: PolicyHandler) -> PolicyHandler:
            # Register the policy
            registered = RegisteredPolicy(
                name=name,
                version=version,
                handler=func,
                events=event_types,
                context_requirements=context_reqs,
                blocking=blocking,
                timeout_ms=timeout_ms,
                description=description,
            )

            self._policies[name] = registered

            # Index by event type for fast lookup
            for event_type in event_types:
                if event_type not in self._event_handlers:
                    self._event_handlers[event_type] = []
                self._event_handlers[event_type].append(
                    registered
                )

            logger.info(
                f"Registered policy: {name} for events: {events}"
            )

            @wraps(func)
            async def wrapper(
                event: PolicyEvent,
            ) -> Verdict:
                return await self._invoke_handler(
                    registered, event
                )

            return wrapper

        return decorator

    async def _invoke_handler(
        self, policy: RegisteredPolicy, event: PolicyEvent
    ) -> Verdict:
        """Invoke a policy handler with timing and error handling."""
        start = time.perf_counter()

        try:
            result = policy.handler(event)
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(
                    result, timeout=policy.timeout_ms / 1000
                )

            elapsed_ms = (
                time.perf_counter() - start
            ) * 1000

            # Enrich verdict with policy metadata
            if isinstance(result, Verdict):
                result.policy_name = policy.name
                result.policy_version = policy.version
                result.evaluation_ms = elapsed_ms
                return result
            else:
                # Handler returned something weird
                logger.warning(
                    f"Policy {policy.name} returned non-Verdict: {type(result)}"
                )
                return Verdict.allow(
                    reasoning="Policy returned invalid type"
                )

        except asyncio.TimeoutError:
            elapsed_ms = (
                time.perf_counter() - start
            ) * 1000
            logger.warning(
                f"Policy {policy.name} timed out after {elapsed_ms:.1f}ms"
            )
            return Verdict(
                decision=Decision.ALLOW,
                reasoning=f"Policy timed out after {policy.timeout_ms}ms",
                policy_name=policy.name,
                evaluation_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (
                time.perf_counter() - start
            ) * 1000
            logger.error(
                f"Policy {policy.name} raised exception: {e}"
            )
            return Verdict(
                decision=Decision.ALLOW,
                reasoning=f"Policy error: {str(e)}",
                policy_name=policy.name,
                evaluation_ms=elapsed_ms,
            )

    async def evaluate(
        self, event: PolicyEvent
    ) -> list[Verdict]:
        """
        Evaluate all applicable policies for an event.

        Returns list of verdicts from all matching policies.
        Composition (how to combine verdicts) is handled by the runtime.
        """
        handlers = self._event_handlers.get(event.type, [])

        if not handlers:
            return [
                Verdict.allow(
                    reasoning="No policies registered for this event"
                )
            ]

        # Run all handlers
        # TODO: Add parallel execution option
        verdicts = []
        for policy in handlers:
            verdict = await self._invoke_handler(
                policy, event
            )
            verdicts.append(verdict)

        return verdicts

    def get_manifest(self) -> PolicyManifest:
        """Generate the server manifest for registration."""
        policy_defs = [
            PolicyDefinition(
                name=p.name,
                version=p.version,
                description=p.description,
                events=p.events,
                context_requirements=p.context_requirements,
                blocking=p.blocking,
                timeout_ms=p.timeout_ms,
            )
            for p in self._policies.values()
        ]

        return PolicyManifest(
            server_name=self.name,
            server_version=self.version,
            description=self.description,
            policies=policy_defs,
        )

    # =========================================================================
    # TRANSPORTS
    # =========================================================================

    def run(self, transport: str = "stdio"):
        """
        Start the policy server.

        Args:
            transport: "stdio" (default), "http", or "websocket"
        """
        if transport == "stdio":
            asyncio.run(self._run_stdio())
        elif transport == "http":
            raise NotImplementedError(
                "HTTP transport coming soon"
            )
        elif transport == "websocket":
            raise NotImplementedError(
                "WebSocket transport coming soon"
            )
        else:
            raise ValueError(
                f"Unknown transport: {transport}"
            )

    async def _run_stdio(self):
        """
        Run server over stdio (like MCP).

        Protocol:
        - One JSON message per line
        - Request: {"type": "evaluate", "event": {...}}
        - Response: {"type": "verdict", "verdicts": [...]}
        """
        logger.info(
            f"APL Policy Server '{self.name}' starting on stdio..."
        )

        # Send manifest on startup
        manifest = self.get_manifest()
        await self._write_message(
            {
                "type": "manifest",
                "manifest": self._serialize(manifest),
            }
        )

        # Read events from stdin
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(
            lambda: protocol, sys.stdin
        )

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break

                message = json.loads(line.decode())
                await self._handle_message(message)

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
            except Exception as e:
                logger.error(f"Error handling message: {e}")

    async def _handle_message(self, message: dict):
        """Handle an incoming message."""
        msg_type = message.get("type")

        if msg_type == "evaluate":
            event = self._deserialize_event(
                message.get("event", {})
            )
            verdicts = await self.evaluate(event)
            await self._write_message(
                {
                    "type": "verdicts",
                    "event_id": event.id,
                    "verdicts": [
                        self._serialize(v) for v in verdicts
                    ],
                }
            )

        elif msg_type == "ping":
            await self._write_message({"type": "pong"})

        elif msg_type == "shutdown":
            logger.info("Shutdown requested")
            sys.exit(0)

        else:
            logger.warning(
                f"Unknown message type: {msg_type}"
            )

    async def _write_message(self, message: dict):
        """Write a JSON message to stdout."""
        line = json.dumps(message) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()

    def _serialize(self, obj: Any) -> dict:
        """Serialize a dataclass to dict."""
        if hasattr(obj, "__dataclass_fields__"):
            result = {}
            for field_name in obj.__dataclass_fields__:
                value = getattr(obj, field_name)
                if value is not None:
                    result[field_name] = self._serialize(
                        value
                    )
            return result
        elif isinstance(obj, list):
            return [self._serialize(item) for item in obj]
        elif isinstance(obj, dict):
            return {
                k: self._serialize(v)
                for k, v in obj.items()
            }
        elif hasattr(obj, "value"):  # Enum
            return obj.value
        else:
            return obj

    def _deserialize_event(self, data: dict) -> PolicyEvent:
        """Deserialize a dict to PolicyEvent."""
        from datetime import datetime

        from .types import (
            EventPayload,
            FunctionCall,
            Message,
            SessionMetadata,
            ToolCall,
        )

        # Parse messages
        messages = []
        for m in data.get("messages", []):
            tool_calls = None
            if m.get("tool_calls"):
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        type=tc.get("type", "function"),
                        function=FunctionCall(
                            name=tc["function"]["name"],
                            arguments=tc["function"][
                                "arguments"
                            ],
                        ),
                    )
                    for tc in m["tool_calls"]
                ]

            messages.append(
                Message(
                    role=m["role"],
                    content=m.get("content"),
                    name=m.get("name"),
                    tool_calls=tool_calls,
                    tool_call_id=m.get("tool_call_id"),
                )
            )

        # Parse metadata
        meta_data = data.get("metadata", {})
        metadata = SessionMetadata(
            session_id=meta_data.get(
                "session_id", str(uuid.uuid4())
            ),
            user_id=meta_data.get("user_id"),
            agent_id=meta_data.get("agent_id"),
            token_count=meta_data.get("token_count", 0),
            token_budget=meta_data.get("token_budget"),
            cost_usd=meta_data.get("cost_usd", 0.0),
            cost_budget_usd=meta_data.get(
                "cost_budget_usd"
            ),
            user_roles=meta_data.get("user_roles", []),
            user_region=meta_data.get("user_region"),
            compliance_tags=meta_data.get(
                "compliance_tags", []
            ),
            custom=meta_data.get("custom", {}),
        )

        # Parse payload
        payload_data = data.get("payload", {})
        payload = EventPayload(
            tool_name=payload_data.get("tool_name"),
            tool_args=payload_data.get("tool_args"),
            tool_result=payload_data.get("tool_result"),
            tool_error=payload_data.get("tool_error"),
            llm_model=payload_data.get("llm_model"),
            llm_response=payload_data.get("llm_response"),
            llm_tokens_used=payload_data.get(
                "llm_tokens_used"
            ),
            output_text=payload_data.get("output_text"),
            output_structured=payload_data.get(
                "output_structured"
            ),
            plan=payload_data.get("plan"),
            target_agent=payload_data.get("target_agent"),
            source_agent=payload_data.get("source_agent"),
            handoff_payload=payload_data.get(
                "handoff_payload"
            ),
        )

        return PolicyEvent(
            id=data.get("id", str(uuid.uuid4())),
            type=EventType(
                data.get("type", "input.received")
            ),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if "timestamp" in data
                else datetime.utcnow()
            ),
            messages=messages,
            payload=payload,
            metadata=metadata,
        )
