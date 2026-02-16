from aiohttp import web

from .evaluate_route import (
    EvaluateRouteHandler,
    handle_evaluate,
)
from .health_route import handle_health
from .manifest_route import handle_manifest
from .metrics_route import handle_metrics
from .sse_route import handle_server_sent_events


def register_all_routes(app: web.Application) -> None:
    app.router.add_post("/evaluate", handle_evaluate)
    app.router.add_get("/manifest", handle_manifest)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_get(
        "/events", handle_server_sent_events
    )
    app.router.add_get(
        "/", lambda r: web.HTTPFound("/health")
    )


__all__ = [
    "register_all_routes",
    "EvaluateRouteHandler",
    "handle_evaluate",
    "handle_manifest",
    "handle_health",
    "handle_metrics",
    "handle_server_sent_events",
]
