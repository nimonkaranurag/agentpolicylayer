import json

from aiohttp import web
from aiohttp.web import middleware


@middleware
async def error_middleware(request: web.Request, handler):
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
        if "metrics" in request.app:
            request.app["metrics"].record_error()
        if "logger" in request.app:
            request.app["logger"].error(f"Unhandled error: {e}", exc_info=True)
        return web.json_response(
            {"error": "Internal server error", "detail": str(e)},
            status=500,
        )
