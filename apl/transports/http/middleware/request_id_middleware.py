import uuid

from aiohttp import web
from aiohttp.web import middleware


@middleware
async def request_id_middleware(request: web.Request, handler):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request["request_id"] = request_id

    response = await handler(request)
    response.headers["X-Request-ID"] = request_id

    return response
