from aiohttp import web
from aiohttp.web import middleware


@middleware
async def cors_middleware(
    request: web.Request, handler
):
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)

    response.headers["Access-Control-Allow-Origin"] = (
        "*"
    )
    response.headers[
        "Access-Control-Allow-Methods"
    ] = "GET, POST, OPTIONS"
    response.headers[
        "Access-Control-Allow-Headers"
    ] = "Content-Type, Authorization, X-Request-ID"
    response.headers["Access-Control-Max-Age"] = (
        "86400"
    )

    return response
