from aiohttp import web


async def handle_health(
    request: web.Request,
) -> web.Response:
    server = request.app["server"]
    metrics = request.app.get("metrics")

    response = {
        "status": "healthy",
        "server": server.name,
        "version": server.version,
        "policies_loaded": len(
            server.registry.all_policies()
        ),
    }

    if metrics:
        response["uptime_seconds"] = (
            metrics.uptime_seconds
        )
        response["requests_total"] = (
            metrics.requests_total
        )

    return web.json_response(response)
