from aiohttp import web


async def handle_manifest(
    request: web.Request,
) -> web.Response:
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
