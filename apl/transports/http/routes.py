"""
HTTP route handlers for the policy server.

Co-located here (aiohttp/Django idiom) rather than one file per endpoint. The only
endpoint with a request body is ``POST /evaluate``; it validates input and answers
malformed requests with a 4xx envelope instead of a 500 that leaks the exception.
"""

from __future__ import annotations

import asyncio
import time

from aiohttp import web
from pydantic import ValidationError

from apl.composition import VerdictComposer
from apl.metrics import export_metrics_to_prometheus
from apl.serialization import event_from_wire, to_wire

from .middleware import error_response

# Composition here is stateless; one instance is reused across requests. Wiring
# server-side CompositionConfig is the server composer's concern.
_COMPOSER = VerdictComposer()


async def handle_evaluate(request: web.Request) -> web.StreamResponse:
    server = request.app["server"]
    metrics = request.app.get("metrics")
    logger = request.app.get("logger")

    if request.content_type != "application/json":
        return error_response(
            request,
            status=415,
            code="unsupported_media_type",
            message="Content-Type must be application/json.",
        )

    start = time.perf_counter()

    # A malformed body raises json.JSONDecodeError -> 400 (error_middleware).
    data = await request.json()

    try:
        event = event_from_wire(data)
    except (ValidationError, ValueError, KeyError, TypeError):
        # Bad-but-present fields (unknown event type, wrong shape) are a client
        # error, not a server fault. Return 400 without echoing the exception.
        return error_response(
            request,
            status=400,
            code="invalid_request",
            message="Request payload is not a valid policy event.",
        )

    if logger:
        logger.event_received(event.type.value, event.id)

    verdicts = await server.evaluate(event)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if logger:
        for v in verdicts:
            logger.policy_evaluated(v.policy_name or "unknown", v, v.evaluation_ms)

    composed = _COMPOSER.compose(verdicts)

    if metrics:
        metrics.record_request(event.type.value, composed.decision.value, elapsed_ms)

    if logger:
        logger.composition_result(len(verdicts), composed.decision, elapsed_ms)

    return web.json_response(
        {
            "event_id": event.id,
            "verdicts": [to_wire(v) for v in verdicts],
            "composed_verdict": to_wire(composed),
            "evaluation_ms": elapsed_ms,
        }
    )


async def handle_manifest(request: web.Request) -> web.StreamResponse:
    server = request.app["server"]
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


async def handle_health(request: web.Request) -> web.StreamResponse:
    server = request.app["server"]
    metrics = request.app.get("metrics")

    response = {
        "status": "healthy",
        "server": server.name,
        "version": server.version,
        "policies_loaded": len(server.registry.all_policies()),
    }

    if metrics:
        response["uptime_seconds"] = metrics.uptime_seconds
        response["requests_total"] = metrics.requests_total

    return web.json_response(response)


async def handle_metrics(request: web.Request) -> web.StreamResponse:
    metrics = request.app.get("metrics")

    if metrics is None:
        return web.Response(
            text="# No metrics available\n",
            content_type="text/plain; version=0.0.4",
        )

    return web.Response(
        text=export_metrics_to_prometheus(metrics),
        content_type="text/plain; version=0.0.4",
    )


async def handle_server_sent_events(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"

    await response.prepare(request)

    try:
        while True:
            await response.write(b": keepalive\n\n")
            await asyncio.sleep(15)
    except asyncio.CancelledError:
        pass

    return response


async def handle_root(request: web.Request) -> web.StreamResponse:
    # aiohttp 3.x requires a coroutine handler (the previous sync `lambda` failed at
    # request time when "/" was hit) and wants redirects *raised*, not returned —
    # returning an HTTPException is deprecated. Raising issues the 302 to /health.
    raise web.HTTPFound("/health")


def register_all_routes(app: web.Application) -> None:
    app.router.add_post("/evaluate", handle_evaluate)
    app.router.add_get("/manifest", handle_manifest)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_get("/events", handle_server_sent_events)
    app.router.add_get("/", handle_root)


__all__ = [
    "register_all_routes",
    "handle_evaluate",
    "handle_manifest",
    "handle_health",
    "handle_metrics",
    "handle_server_sent_events",
]
