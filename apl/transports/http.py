"""
APL HTTP Transport

Production-ready HTTP server for APL policy servers.

Features:
- RESTful API for policy evaluation
- Server-Sent Events (SSE) for streaming verdicts
- Health checks and metrics endpoints
- CORS support for browser clients
- Request validation and error handling

Endpoints:
    POST /evaluate          Evaluate policies for an event
    GET  /manifest          Get server manifest
    GET  /health            Health check
    GET  /metrics           Prometheus-compatible metrics
    GET  /events            SSE stream for real-time verdicts

Example:
    curl -X POST http://localhost:8080/evaluate \\
        -H "Content-Type: application/json" \\
        -d '{"type": "output.pre_send", "payload": {"output_text": "test"}}'
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web
from aiohttp.web import middleware

from ..logging import APLLogger
from ..server import PolicyServer
from ..types import (
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    SessionMetadata,
    Verdict,
)


def kill_port(port: int) -> bool:
    import sys

    try:
        if (
            sys.platform
            == "darwin" | sys.platform.startswith("linux")
        ):
            # macOS / Linux
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except (ProcessLookupError, ValueError):
                        pass
                return True
        elif sys.platform == "win32":
            # Windows
            result = subprocess.run(
                [
                    "netstat",
                    "-ano",
                    "|",
                    "findstr",
                    f":{port}",
                ],
                capture_output=True,
                text=True,
                shell=True,
            )
            # Parse PID from netstat output and kill
            for line in result.stdout.strip().split("\n"):
                if f":{port}" in line:
                    parts = line.split()
                    if parts:
                        try:
                            pid = int(parts[-1])
                            subprocess.run(
                                [
                                    "taskkill",
                                    "/F",
                                    "/PID",
                                    str(pid),
                                ],
                                capture_output=True,
                            )
                        except (ValueError, IndexError):
                            pass
            return True
    except Exception:
        pass
    return False


# =============================================================================
# METRICS
# =============================================================================


@dataclass
class ServerMetrics:
    """Metrics for the HTTP server."""

    requests_total: int = 0
    requests_by_event: dict[str, int] = field(
        default_factory=dict
    )
    verdicts_by_decision: dict[str, int] = field(
        default_factory=dict
    )
    latency_sum_ms: float = 0.0
    latency_count: int = 0
    errors_total: int = 0
    start_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def record_request(
        self,
        event_type: str,
        decision: str,
        latency_ms: float,
    ):
        """Record a request."""
        self.requests_total += 1
        self.requests_by_event[event_type] = (
            self.requests_by_event.get(event_type, 0) + 1
        )
        self.verdicts_by_decision[decision] = (
            self.verdicts_by_decision.get(decision, 0) + 1
        )
        self.latency_sum_ms += latency_ms
        self.latency_count += 1

    def record_error(self):
        """Record an error."""
        self.errors_total += 1

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if self.latency_count == 0:
            return 0.0
        return self.latency_sum_ms / self.latency_count

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = [
            "# HELP apl_requests_total Total number of policy evaluation requests",
            "# TYPE apl_requests_total counter",
            f"apl_requests_total {self.requests_total}",
            "",
            "# HELP apl_errors_total Total number of errors",
            "# TYPE apl_errors_total counter",
            f"apl_errors_total {self.errors_total}",
            "",
            "# HELP apl_latency_ms_avg Average evaluation latency in milliseconds",
            "# TYPE apl_latency_ms_avg gauge",
            f"apl_latency_ms_avg {self.avg_latency_ms:.2f}",
            "",
            "# HELP apl_requests_by_event_total Requests by event type",
            "# TYPE apl_requests_by_event_total counter",
        ]

        for (
            event_type,
            count,
        ) in self.requests_by_event.items():
            lines.append(
                f'apl_requests_by_event_total{{event="{event_type}"}} {count}'
            )

        lines.extend(
            [
                "",
                "# HELP apl_verdicts_by_decision_total Verdicts by decision",
                "# TYPE apl_verdicts_by_decision_total counter",
            ]
        )

        for (
            decision,
            count,
        ) in self.verdicts_by_decision.items():
            lines.append(
                f'apl_verdicts_by_decision_total{{decision="{decision}"}} {count}'
            )

        return "\n".join(lines)


# =============================================================================
# MIDDLEWARE
# =============================================================================


@middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware for browser clients."""
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, OPTIONS"
    )
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Request-ID"
    )
    response.headers["Access-Control-Max-Age"] = "86400"

    return response


@middleware
async def request_id_middleware(
    request: web.Request, handler
):
    """Add request ID for tracing."""
    request_id = request.headers.get(
        "X-Request-ID", str(uuid.uuid4())
    )
    request["request_id"] = request_id

    response = await handler(request)
    response.headers["X-Request-ID"] = request_id

    return response


@middleware
async def error_middleware(request: web.Request, handler):
    """Global error handling."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except json.JSONDecodeError as e:
        return web.json_response(
            {"error": "Invalid JSON", "detail": str(e)},
            status=400,
        )
    except Exception as e:
        request.app["metrics"].record_error()
        request.app["logger"].error(
            f"Unhandled error: {e}", exc_info=True
        )
        return web.json_response(
            {
                "error": "Internal server error",
                "detail": str(e),
            },
            status=500,
        )


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


def parse_event_request(data: dict) -> PolicyEvent:
    """
    Parse an event from request JSON.

    Accepts both full PolicyEvent format and simplified format:

    Full format:
        {
            "id": "...",
            "type": "tool.pre_invoke",
            "timestamp": "...",
            "messages": [...],
            "payload": {...},
            "metadata": {...}
        }

    Simplified format:
        {
            "type": "tool.pre_invoke",
            "payload": {...}
        }
    """
    # Parse messages
    messages = []
    for m in data.get("messages", []):
        messages.append(
            Message(
                role=m["role"],
                content=m.get("content"),
                name=m.get("name"),
                tool_call_id=m.get("tool_call_id"),
            )
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
        llm_tokens_used=payload_data.get("llm_tokens_used"),
        output_text=payload_data.get("output_text"),
        output_structured=payload_data.get(
            "output_structured"
        ),
        plan=payload_data.get("plan"),
        target_agent=payload_data.get("target_agent"),
        source_agent=payload_data.get("source_agent"),
        handoff_payload=payload_data.get("handoff_payload"),
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
        cost_budget_usd=meta_data.get("cost_budget_usd"),
        user_roles=meta_data.get("user_roles", []),
        user_region=meta_data.get("user_region"),
        compliance_tags=meta_data.get(
            "compliance_tags", []
        ),
        custom=meta_data.get("custom", {}),
    )

    # Parse timestamp
    timestamp_str = data.get("timestamp")
    if timestamp_str:
        timestamp = datetime.fromisoformat(
            timestamp_str.replace("Z", "+00:00")
        )
    else:
        timestamp = datetime.now(timezone.utc)

    return PolicyEvent(
        id=data.get("id", str(uuid.uuid4())),
        type=EventType(data["type"]),
        timestamp=timestamp,
        messages=messages,
        payload=payload,
        metadata=metadata,
    )


def serialize_verdict(verdict: Verdict) -> dict:
    """Serialize a Verdict to JSON-safe dict."""
    result = {
        "decision": verdict.decision.value,
        "confidence": verdict.confidence,
        "reasoning": verdict.reasoning,
        "policy_name": verdict.policy_name,
        "policy_version": verdict.policy_version,
        "evaluation_ms": verdict.evaluation_ms,
    }

    if verdict.modification:
        result["modification"] = {
            "target": verdict.modification.target,
            "operation": verdict.modification.operation,
            "value": verdict.modification.value,
            "path": verdict.modification.path,
        }

    if verdict.escalation:
        result["escalation"] = {
            "type": verdict.escalation.type,
            "prompt": verdict.escalation.prompt,
            "fallback_action": verdict.escalation.fallback_action,
            "timeout_ms": verdict.escalation.timeout_ms,
            "options": verdict.escalation.options,
        }

    if verdict.trace:
        result["trace"] = verdict.trace

    return result


# =============================================================================
# ROUTE HANDLERS
# =============================================================================


async def handle_evaluate(
    request: web.Request,
) -> web.Response:
    """
    Evaluate policies for an event.

    POST /evaluate

    Request body:
        {
            "type": "tool.pre_invoke",
            "payload": {
                "tool_name": "delete_file",
                "tool_args": {"path": "/data"}
            },
            "metadata": {
                "session_id": "...",
                "user_id": "..."
            }
        }

    Response:
        {
            "event_id": "...",
            "verdicts": [...],
            "composed_verdict": {...},
            "evaluation_ms": 1.23
        }
    """
    server: PolicyServer = request.app["server"]
    logger: APLLogger = request.app["logger"]
    metrics: ServerMetrics = request.app["metrics"]

    start = time.perf_counter()

    # Parse request
    data = await request.json()

    if "type" not in data:
        return web.json_response(
            {"error": "Missing required field: type"},
            status=400,
        )

    event = parse_event_request(data)
    logger.event_received(event.type.value, event.id)

    # Evaluate policies
    verdicts = await server.evaluate(event)

    elapsed_ms = (time.perf_counter() - start) * 1000

    # Log verdicts
    for v in verdicts:
        logger.policy_evaluated(
            v.policy_name or "unknown", v, v.evaluation_ms
        )

    # Compose verdicts (simple deny-overrides for now)
    composed = _compose_verdicts(verdicts)

    # Record metrics
    metrics.record_request(
        event.type.value,
        composed.decision.value,
        elapsed_ms,
    )

    logger.composition_result(
        len(verdicts), composed.decision, elapsed_ms
    )

    return web.json_response(
        {
            "event_id": event.id,
            "verdicts": [
                serialize_verdict(v) for v in verdicts
            ],
            "composed_verdict": serialize_verdict(composed),
            "evaluation_ms": elapsed_ms,
        }
    )


async def handle_manifest(
    request: web.Request,
) -> web.Response:
    """
    Get server manifest.

    GET /manifest
    """
    server: PolicyServer = request.app["server"]
    manifest = server.get_manifest()

    return web.json_response(
        {
            "server_name": manifest.server_name,
            "server_version": manifest.server_version,
            "protocol_version": manifest.protocol_version,
            "description": manifest.description,
            "policies": [
                {
                    "name": p.name,
                    "version": p.version,
                    "description": p.description,
                    "events": [e.value for e in p.events],
                    "blocking": p.blocking,
                    "timeout_ms": p.timeout_ms,
                }
                for p in manifest.policies
            ],
        }
    )


async def handle_health(
    request: web.Request,
) -> web.Response:
    """
    Health check endpoint.

    GET /health
    """
    server: PolicyServer = request.app["server"]
    metrics: ServerMetrics = request.app["metrics"]

    uptime = (
        datetime.now(timezone.utc) - metrics.start_time
    ).total_seconds()

    return web.json_response(
        {
            "status": "healthy",
            "server": server.name,
            "version": server.version,
            "uptime_seconds": uptime,
            "policies_loaded": len(server._policies),
            "requests_total": metrics.requests_total,
        }
    )


async def handle_metrics(
    request: web.Request,
) -> web.Response:
    """
    Prometheus-compatible metrics.

    GET /metrics
    """
    metrics: ServerMetrics = request.app["metrics"]

    return web.Response(
        text=metrics.to_prometheus(),
        content_type="text/plain; version=0.0.4",
    )


async def handle_events_sse(
    request: web.Request,
) -> web.StreamResponse:
    """
    Server-Sent Events stream for real-time verdicts.

    GET /events

    Streams events as:
        event: verdict
        data: {"policy": "...", "decision": "allow", ...}
    """
    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"

    await response.prepare(request)

    # Send keepalive every 15 seconds
    try:
        while True:
            await response.write(b": keepalive\n\n")
            await asyncio.sleep(15)
    except asyncio.CancelledError:
        pass

    return response


# =============================================================================
# COMPOSITION
# =============================================================================


def _compose_verdicts(verdicts: list[Verdict]) -> Verdict:
    """Simple deny-overrides composition."""
    if not verdicts:
        return Verdict.allow(
            reasoning="No policies evaluated"
        )

    # Check for denies
    denies = [
        v for v in verdicts if v.decision == Decision.DENY
    ]
    if denies:
        return denies[0]

    # Check for escalations
    escalations = [
        v
        for v in verdicts
        if v.decision == Decision.ESCALATE
    ]
    if escalations:
        return escalations[0]

    # Check for modifications
    modifications = [
        v for v in verdicts if v.decision == Decision.MODIFY
    ]
    if modifications:
        return modifications[0]

    # All allowed
    return Verdict.allow(reasoning="All policies allowed")


# =============================================================================
# SERVER SETUP
# =============================================================================


def create_app(
    server: PolicyServer, logger: APLLogger
) -> web.Application:
    """
    Create the aiohttp application.

    Args:
        server: PolicyServer instance
        logger: APLLogger instance

    Returns:
        Configured aiohttp Application
    """
    app = web.Application(
        middlewares=[
            error_middleware,
            cors_middleware,
            request_id_middleware,
        ]
    )

    # Store references
    app["server"] = server
    app["logger"] = logger
    app["metrics"] = ServerMetrics()

    # Routes
    app.router.add_post("/evaluate", handle_evaluate)
    app.router.add_get("/manifest", handle_manifest)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_get("/events", handle_events_sse)

    # Root redirect to health
    app.router.add_get(
        "/", lambda r: web.HTTPFound("/health")
    )

    return app


async def run_http_server(
    server: PolicyServer,
    host: str = "0.0.0.0",
    port: int = 8080,
    logger: Optional[APLLogger] = None,
):
    """
    Run the HTTP server.

    Args:
        server: PolicyServer instance
        host: Host to bind to
        port: Port to listen on
        logger: Optional APLLogger instance
    """
    if logger is None:
        from ..logging import setup_logging

        logger = setup_logging()

    app = create_app(server, logger)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    try:
        await site.start()
    except OSError as e:
        if (
            e.errno == 48 or e.errno == 98
        ):  # 48=macOS, 98=Linux "address in use"
            logger.warning(
                f"Port {port} in use, attempting to free it..."
            )
            if kill_port(port):
                await asyncio.sleep(
                    0.5
                )  # Give OS time to release
                try:
                    await site.start()
                except OSError:
                    logger.error(
                        f"Could not bind to port {port} even after killing existing process"
                    )
                    raise
            else:
                raise
        else:
            raise

    logger.server_started("http", f"{host}:{port}")

    # Keep running until cancelled
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
        logger.server_stopped()
