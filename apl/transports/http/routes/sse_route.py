import asyncio

from aiohttp import web


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
