"""
HTTP middleware stack for the policy server.

Ordered outermost → innermost as ``MIDDLEWARE_STACK``:

1. ``request_id_middleware`` — assigns/propagates ``X-Request-ID`` and stamps it
   on *every* response, including error responses (it is the outermost layer, so
   it sees them).
2. ``cors_middleware`` — reflects an ``Origin`` only when it is on the configured
   allow-list (``app["cors_origins"]``); no wildcard by default.
3. ``error_middleware`` — converts uncaught exceptions into a stable JSON error
   envelope without echoing the underlying exception to the client.
4. ``auth_middleware`` — when ``app["auth_token"]`` is set, requires a matching
   ``Authorization: Bearer`` token on non-public routes.

Config is read from ``request.app`` so the middlewares stay plain functions and
the app factory is the single place that wires policy.
"""

from __future__ import annotations

import hmac
import json
import uuid

from aiohttp import web
from aiohttp.web import middleware

# Routes reachable without credentials even when auth is enabled: liveness
# probes and the root redirect must work for orchestrators/health checks.
PUBLIC_PATHS = frozenset({"/health", "/"})


def error_response(
    request: web.Request,
    *,
    status: int,
    code: str,
    message: str,
) -> web.Response:
    """
    Build the stable JSON error envelope shared by middleware and routes.

    The body never includes the raw exception text — only a machine-readable ``code``, a
    fixed human ``message``, and the request id for correlation.
    """
    return web.json_response(
        {
            "error": code,
            "message": message,
            "request_id": request.get("request_id", "-"),
        },
        status=status,
    )


# Generic Server header: aiohttp's default leaks the aiohttp/Python versions,
# which is needless reconnaissance. Overwrite it with a fixed token.
_SERVER_HEADER = "apl"


@middleware
async def request_id_middleware(request: web.Request, handler):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request["request_id"] = request_id

    try:
        response = await handler(request)
    except web.HTTPException as exc:
        exc.headers["X-Request-ID"] = request_id
        exc.headers["Server"] = _SERVER_HEADER
        raise

    response.headers["X-Request-ID"] = request_id
    response.headers["Server"] = _SERVER_HEADER
    return response


def _allowed_origin(request: web.Request) -> str | None:
    origin = request.headers.get("Origin")
    allow_list = request.app.get("cors_origins") or []
    if not origin or not allow_list:
        return None
    if origin in allow_list or "*" in allow_list:
        # Reflect the concrete origin (never the literal "*") so the policy is
        # explicit and compatible with credentialed requests.
        return origin
    return None


def _apply_cors_headers(response: web.StreamResponse, origin: str) -> None:
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Request-ID"
    )
    response.headers["Access-Control-Max-Age"] = "86400"


@middleware
async def cors_middleware(request: web.Request, handler):
    origin = _allowed_origin(request)

    if request.method == "OPTIONS":
        # Preflight: 204 when the origin is allowed, 403 otherwise. Preflight is
        # never authenticated, so it short-circuits before auth_middleware.
        response = web.Response(status=204 if origin else 403)
        if origin:
            _apply_cors_headers(response, origin)
        return response

    try:
        response = await handler(request)
    except web.HTTPException as exc:
        if origin:
            _apply_cors_headers(exc, origin)
        raise

    if origin:
        _apply_cors_headers(response, origin)
    return response


@middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPRequestEntityTooLarge:
        return error_response(
            request,
            status=413,
            code="payload_too_large",
            message="Request body exceeds the configured size limit.",
        )
    except web.HTTPException:
        raise
    except json.JSONDecodeError:
        return error_response(
            request,
            status=400,
            code="invalid_json",
            message="Request body is not valid JSON.",
        )
    except Exception as exc:
        # Log the detail server-side; never echo it to the client.
        if "metrics" in request.app:
            request.app["metrics"].record_error()
        if "logger" in request.app:
            request.app["logger"].error(f"Unhandled error: {exc}", exc_info=True)
        return error_response(
            request,
            status=500,
            code="internal_error",
            message="Internal server error.",
        )


def _bearer_token(authorization: str) -> str | None:
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


@middleware
async def auth_middleware(request: web.Request, handler):
    token = request.app.get("auth_token")
    needs_auth = (
        token and request.method != "OPTIONS" and request.path not in PUBLIC_PATHS
    )
    if needs_auth:
        provided = _bearer_token(request.headers.get("Authorization", ""))
        if provided is None or not hmac.compare_digest(provided, token):
            return error_response(
                request,
                status=401,
                code="unauthorized",
                message="Missing or invalid credentials.",
            )
    return await handler(request)


# Outermost first. request_id must wrap error so the id is present on the error
# path; cors wraps error so even error responses carry CORS headers.
MIDDLEWARE_STACK = [
    request_id_middleware,
    cors_middleware,
    error_middleware,
    auth_middleware,
]

__all__ = [
    "MIDDLEWARE_STACK",
    "PUBLIC_PATHS",
    "error_response",
    "request_id_middleware",
    "cors_middleware",
    "error_middleware",
    "auth_middleware",
]
