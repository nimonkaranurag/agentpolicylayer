from aiohttp import web

from apl.metrics import export_metrics_to_prometheus


async def handle_metrics(request: web.Request) -> web.Response:
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
