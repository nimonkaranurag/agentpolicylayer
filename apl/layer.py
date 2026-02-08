"""
APL Policy Layer

This is what agent runtime developers use to connect policies to their agents.
It handles:
1. Connecting to policy servers
2. Routing events to appropriate policies
3. Composing verdicts from multiple policies
4. Framework-specific adapters
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
import uuid
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

from .types import (
    CompositionConfig,
    CompositionMode,
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    PolicyManifest,
    SessionMetadata,
    Verdict,
)

logger = logging.getLogger("apl")


# =============================================================================
# POLICY CLIENT - Connection to a policy server
# =============================================================================


class PolicyClient:
    """
    Client connection to a single policy server.
    Handles communication over various transports.
    """

    def __init__(self, uri: str):
        """
        Connect to a policy server.

        Supported URI formats:
        - stdio://./path/to/server.py  (spawn and communicate via stdio)
        - stdio://npx @apl/pii-filter  (run npx command)
        - http://localhost:8080        (HTTP transport)
        - ws://localhost:8080          (WebSocket transport)
        """
        self.uri = uri
        self.manifest: Optional[PolicyManifest] = None
        self._process: Optional[subprocess.Popen] = None
        self._connected = False

    async def connect(self):
        """Establish connection to the policy server."""
        if self.uri.startswith("stdio://"):
            await self._connect_stdio()
        elif self.uri.startswith(
            "http://"
        ) or self.uri.startswith("https://"):
            await self._connect_http()
        else:
            raise ValueError(
                f"Unsupported URI scheme: {self.uri}"
            )

    async def _connect_stdio(self):
        """Connect via stdio transport."""
        command = self.uri[len("stdio://") :]

        # Handle different command formats
        if command.startswith("npx "):
            args = command.split()
        elif command.startswith("./"):
            # Local Python script
            args = [sys.executable, command]
        else:
            args = command.split()

        logger.info(f"Spawning policy server: {args}")

        self._process = (
            await asyncio.create_subprocess_exec(
                *args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )

        # Read manifest from first message
        line = await self._process.stdout.readline()
        if line:
            message = json.loads(line.decode())
            if message.get("type") == "manifest":
                self.manifest = self._parse_manifest(
                    message.get("manifest", {})
                )
                logger.info(
                    f"Connected to '{self.manifest.server_name}' with {len(self.manifest.policies)} policies"
                )

        self._connected = True

    async def _connect_http(self):
        """Connect via HTTP transport."""
        # TODO: Implement HTTP transport
        raise NotImplementedError(
            "HTTP transport coming soon"
        )

    async def evaluate(
        self, event: PolicyEvent
    ) -> list[Verdict]:
        """
        Send an event to the policy server and get verdicts.
        """
        if not self._connected:
            await self.connect()

        if self.uri.startswith("stdio://"):
            return await self._evaluate_stdio(event)
        else:
            return await self._evaluate_http(event)

    async def _evaluate_stdio(
        self, event: PolicyEvent
    ) -> list[Verdict]:
        """Evaluate via stdio transport."""
        # Serialize and send event
        message = {
            "type": "evaluate",
            "event": self._serialize_event(event),
        }

        line = json.dumps(message) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

        # Read response
        response_line = (
            await self._process.stdout.readline()
        )
        if not response_line:
            return [
                Verdict.allow(
                    reasoning="No response from policy server"
                )
            ]

        response = json.loads(response_line.decode())

        if response.get("type") == "verdicts":
            return [
                self._parse_verdict(v)
                for v in response.get("verdicts", [])
            ]
        else:
            logger.warning(
                f"Unexpected response type: {response.get('type')}"
            )
            return [
                Verdict.allow(
                    reasoning="Unexpected response from policy server"
                )
            ]

    async def _evaluate_http(
        self, event: PolicyEvent
    ) -> list[Verdict]:
        """Evaluate via HTTP transport."""
        raise NotImplementedError(
            "HTTP transport coming soon"
        )

    async def close(self):
        """Close the connection."""
        if self._process:
            self._process.terminate()
            await self._process.wait()
        self._connected = False

    def _serialize_event(self, event: PolicyEvent) -> dict:
        """Serialize PolicyEvent to dict for transmission."""
        return {
            "id": event.id,
            "type": event.type.value,
            "timestamp": event.timestamp.isoformat(),
            "messages": [
                self._serialize_message(m)
                for m in event.messages
            ],
            "payload": self._serialize_payload(
                event.payload
            ),
            "metadata": self._serialize_metadata(
                event.metadata
            ),
        }

    def _serialize_message(self, msg: Message) -> dict:
        result = {"role": msg.role}
        if msg.content is not None:
            result["content"] = msg.content
        if msg.name:
            result["name"] = msg.name
        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            result["tool_call_id"] = msg.tool_call_id
        return result

    def _serialize_payload(
        self, payload: EventPayload
    ) -> dict:
        result = {}
        for field_name in payload.__dataclass_fields__:
            value = getattr(payload, field_name)
            if value is not None:
                result[field_name] = value
        return result

    def _serialize_metadata(
        self, metadata: SessionMetadata
    ) -> dict:
        return {
            "session_id": metadata.session_id,
            "user_id": metadata.user_id,
            "agent_id": metadata.agent_id,
            "token_count": metadata.token_count,
            "token_budget": metadata.token_budget,
            "cost_usd": metadata.cost_usd,
            "cost_budget_usd": metadata.cost_budget_usd,
            "user_roles": metadata.user_roles,
            "user_region": metadata.user_region,
            "compliance_tags": metadata.compliance_tags,
            "custom": metadata.custom,
        }

    def _parse_manifest(self, data: dict) -> PolicyManifest:
        """Parse manifest from dict."""
        from .types import (
            ContextRequirement,
            PolicyDefinition,
        )

        policies = []
        for p in data.get("policies", []):
            policies.append(
                PolicyDefinition(
                    name=p["name"],
                    version=p.get("version", "1.0.0"),
                    description=p.get("description"),
                    events=[
                        EventType(e)
                        for e in p.get("events", [])
                    ],
                    context_requirements=[
                        ContextRequirement(
                            path=c["path"],
                            required=c.get(
                                "required", True
                            ),
                        )
                        for c in p.get(
                            "context_requirements", []
                        )
                    ],
                    blocking=p.get("blocking", True),
                    timeout_ms=p.get("timeout_ms", 1000),
                )
            )

        return PolicyManifest(
            server_name=data.get("server_name", "unknown"),
            server_version=data.get(
                "server_version", "0.0.0"
            ),
            protocol_version=data.get(
                "protocol_version", "0.1.0"
            ),
            policies=policies,
        )

    def _parse_verdict(self, data: dict) -> Verdict:
        """Parse verdict from dict."""
        from .types import Escalation, Modification

        modification = None
        if data.get("modification"):
            m = data["modification"]
            modification = Modification(
                target=m["target"],
                operation=m["operation"],
                value=m["value"],
                path=m.get("path"),
            )

        escalation = None
        if data.get("escalation"):
            e = data["escalation"]
            escalation = Escalation(
                type=e["type"],
                prompt=e.get("prompt"),
                fallback_action=e.get("fallback_action"),
                timeout_ms=e.get("timeout_ms"),
                options=e.get("options"),
            )

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


# =============================================================================
# POLICY LAYER - The main orchestrator
# =============================================================================


class PolicyLayer:
    """
    The main policy orchestrator.

    Usage:
        policies = PolicyLayer()
        policies.add_server("stdio://./my-policy.py")
        policies.add_server("https://policies.corp.com/compliance")

        # Wrap any agent framework
        agent = policies.wrap(my_agent)

        # Or use decorators
        @policies.on("tool.pre_invoke")
        async def call_tool(tool_name, args):
            ...
    """

    def __init__(
        self,
        composition: CompositionConfig = None,
    ):
        self.composition = (
            composition or CompositionConfig()
        )
        self._clients: list[PolicyClient] = []
        self._connected = False

    def add_server(self, uri: str) -> PolicyLayer:
        """
        Add a policy server.

        Args:
            uri: Policy server URI (stdio://, http://, ws://)

        Returns:
            self for chaining
        """
        client = PolicyClient(uri)
        self._clients.append(client)
        return self

    async def connect(self):
        """Connect to all policy servers."""
        if self._connected:
            return

        await asyncio.gather(
            *[c.connect() for c in self._clients]
        )
        self._connected = True

        # Log summary
        total_policies = sum(
            len(c.manifest.policies) if c.manifest else 0
            for c in self._clients
        )
        logger.info(
            f"PolicyLayer connected: {len(self._clients)} servers, {total_policies} policies"
        )

    async def close(self):
        """Close all connections."""
        await asyncio.gather(
            *[c.close() for c in self._clients]
        )
        self._connected = False

    async def evaluate(
        self,
        event_type: EventType | str,
        messages: list[Message] = None,
        payload: EventPayload = None,
        metadata: SessionMetadata = None,
    ) -> Verdict:
        """
        Evaluate policies for an event.

        Args:
            event_type: The lifecycle event type
            messages: Conversation history (chat/completions format)
            payload: Event-specific payload
            metadata: Session metadata

        Returns:
            Composed verdict from all applicable policies
        """
        if not self._connected:
            await self.connect()

        # Normalize event type
        if isinstance(event_type, str):
            event_type = EventType(event_type)

        # Build event
        event = PolicyEvent(
            id=str(uuid.uuid4()),
            type=event_type,
            timestamp=datetime.utcnow(),
            messages=messages or [],
            payload=payload or EventPayload(),
            metadata=metadata
            or SessionMetadata(
                session_id=str(uuid.uuid4())
            ),
        )

        # Collect verdicts from all servers
        start = time.perf_counter()

        if self.composition.parallel:
            all_verdicts = await asyncio.gather(
                *[c.evaluate(event) for c in self._clients]
            )
            verdicts = [
                v
                for sublist in all_verdicts
                for v in sublist
            ]
        else:
            verdicts = []
            for client in self._clients:
                vs = await client.evaluate(event)
                verdicts.extend(vs)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"Evaluated {len(verdicts)} policies in {elapsed_ms:.1f}ms"
        )

        # Compose verdicts
        return self._compose_verdicts(verdicts)

    def _compose_verdicts(
        self, verdicts: list[Verdict]
    ) -> Verdict:
        """
        Compose multiple verdicts into a single verdict.
        """
        if not verdicts:
            return Verdict.allow(
                reasoning="No policies evaluated"
            )

        mode = self.composition.mode

        if mode == CompositionMode.DENY_OVERRIDES:
            # Any deny wins
            denies = [
                v
                for v in verdicts
                if v.decision == Decision.DENY
            ]
            if denies:
                # Return first deny (or could aggregate reasons)
                return denies[0]

            # Check for escalations
            escalations = [
                v
                for v in verdicts
                if v.decision == Decision.ESCALATE
            ]
            if escalations:
                return escalations[0]

            # Check for modifications (apply first one)
            modifications = [
                v
                for v in verdicts
                if v.decision == Decision.MODIFY
            ]
            if modifications:
                return modifications[0]

            # All allowed
            return Verdict.allow(
                reasoning="All policies allowed"
            )

        elif mode == CompositionMode.UNANIMOUS:
            # All must allow
            for v in verdicts:
                if v.decision == Decision.DENY:
                    return v
                if v.decision == Decision.ESCALATE:
                    return v

            return Verdict.allow(
                reasoning="All policies agreed"
            )

        elif mode == CompositionMode.FIRST_APPLICABLE:
            # First non-observe verdict wins
            for v in verdicts:
                if v.decision != Decision.OBSERVE:
                    return v

            return Verdict.allow(
                reasoning="No applicable policy"
            )

        elif mode == CompositionMode.WEIGHTED:
            # Confidence-weighted voting (for soft constraints)
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
                return (
                    denies[0]
                    if denies
                    else Verdict.deny("Weighted deny")
                )

            return Verdict.allow(
                reasoning=f"Weighted allow ({allow_score:.2f} vs {deny_score:.2f})"
            )

        else:
            return Verdict.allow(
                reasoning="Unknown composition mode"
            )

    # =========================================================================
    # DECORATOR API
    # =========================================================================

    def on(
        self,
        event_type: str,
        messages_from: Callable = None,
    ):
        """
        Decorator to add policy evaluation to a function.

        Usage:
            @policies.on("tool.pre_invoke")
            async def call_tool(tool_name, args):
                # If we get here, policies allowed it
                return execute_tool(tool_name, args)
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Build payload from function args
                # This is a simple heuristic - can be customized
                payload = EventPayload()

                if "tool_name" in kwargs:
                    payload.tool_name = kwargs["tool_name"]
                if "tool_args" in kwargs:
                    payload.tool_args = kwargs["tool_args"]
                if len(args) >= 1:
                    payload.tool_name = args[0]
                if len(args) >= 2:
                    payload.tool_args = args[1]

                # Get messages if extractor provided
                messages = []
                if messages_from:
                    messages = messages_from()

                # Evaluate policies
                verdict = await self.evaluate(
                    event_type=event_type,
                    messages=messages,
                    payload=payload,
                )

                # Handle verdict
                if verdict.decision == Decision.DENY:
                    raise PolicyDenied(verdict)

                if verdict.decision == Decision.ESCALATE:
                    raise PolicyEscalation(verdict)

                if verdict.decision == Decision.MODIFY:
                    # Apply modification
                    if verdict.modification:
                        m = verdict.modification
                        if (
                            m.target == "tool_args"
                            and m.operation == "replace"
                        ):
                            kwargs["tool_args"] = m.value
                        # TODO: Handle other modification types

                return await func(*args, **kwargs)

            return wrapper

        return decorator

    # =========================================================================
    # FRAMEWORK ADAPTERS
    # =========================================================================

    def wrap(self, agent: Any) -> Any:
        """
        Wrap an agent framework to add policy evaluation.

        Supports:
        - LangGraph StateGraph
        - AutoGen agents
        - CrewAI Crew
        - Any object with known method patterns
        """
        agent_type = type(agent).__name__

        # Try to detect framework
        if hasattr(agent, "add_node") and hasattr(
            agent, "add_edge"
        ):
            # Looks like LangGraph
            return self._wrap_langgraph(agent)

        # Add more framework detection here

        logger.warning(
            f"Unknown agent type: {agent_type}, returning unwrapped"
        )
        return agent

    def _wrap_langgraph(self, graph):
        """Wrap a LangGraph StateGraph."""
        # TODO: Implement LangGraph wrapper
        # This would intercept node execution and tool calls
        logger.info("LangGraph wrapper not yet implemented")
        return graph


# =============================================================================
# EXCEPTIONS
# =============================================================================


class PolicyDenied(Exception):
    """Raised when a policy denies an action."""

    def __init__(self, verdict: Verdict):
        self.verdict = verdict
        super().__init__(
            verdict.reasoning or "Policy denied"
        )


class PolicyEscalation(Exception):
    """Raised when a policy requires escalation."""

    def __init__(self, verdict: Verdict):
        self.verdict = verdict
        super().__init__(
            verdict.escalation.prompt
            if verdict.escalation
            else "Escalation required"
        )
