"""
HTTP policy-server transport and aiohttp application factory.

Safe defaults for a guardrails product: binds loopback (``127.0.0.1``), enforces a
request-size limit, and supports an optional bearer-token auth hook and a CORS allow-
list. A port that is already in use raises a clear error — it never kills the owning
process.
"""

from __future__ import annotations

import asyncio
import errno
from typing import TYPE_CHECKING, Optional

from aiohttp import web

from apl.logging import APLLogger, get_logger, setup_logging
from apl.metrics import ServerMetrics
from apl.transports.base_transport import BaseTransport

from .middleware import MIDDLEWARE_STACK
from .routes import register_all_routes

if TYPE_CHECKING:
    from apl.server import PolicyServer

logger = get_logger("transport.http")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_MAX_REQUEST_BYTES = 1024 * 1024  # 1 MiB


def create_http_application(
    server: "PolicyServer",
    *,
    apl_logger: APLLogger | None = None,
    auth_token: Optional[str] = None,
    cors_origins: Optional[list[str]] = None,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
) -> web.Application:
    """
    Build the aiohttp application with the policy server and security config.

    Args:
        server: the policy server whose routes are mounted.
        apl_logger: optional structured logger surfaced to handlers.
        auth_token: when set, non-public routes require this bearer token.
        cors_origins: allow-listed origins; empty means no CORS headers.
        max_request_bytes: hard cap on request body size (413 above it).
    """
    app = web.Application(
        middlewares=MIDDLEWARE_STACK,
        client_max_size=max_request_bytes,
    )

    app["server"] = server
    app["metrics"] = ServerMetrics()
    app["auth_token"] = auth_token
    app["cors_origins"] = list(cors_origins) if cors_origins else []

    if apl_logger:
        app["logger"] = apl_logger

    register_all_routes(app)

    return app


class HTTPTransport(BaseTransport):
    def __init__(
        self,
        server: "PolicyServer",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        auth_token: Optional[str] = None,
        cors_origins: Optional[list[str]] = None,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        apl_logger: APLLogger | None = None,
    ):
        super().__init__(server)
        self._host = host
        self._port = port
        self._auth_token = auth_token
        self._cors_origins = cors_origins
        self._max_request_bytes = max_request_bytes
        self._logger = apl_logger
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def run(self) -> None:
        asyncio.run(self._run_until_stopped())

    async def start(self) -> None:
        if self._logger is None:
            self._logger = setup_logging()

        app = create_http_application(
            self.server,
            apl_logger=self._logger,
            auth_token=self._auth_token,
            cors_origins=self._cors_origins,
            max_request_bytes=self._max_request_bytes,
        )

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self._host, self._port)

        try:
            await self._site.start()
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                logger.error(
                    f"Port {self._port} on {self._host} is already in use. "
                    "Stop the process using it or choose a different port."
                )
            raise

        self._logger.server_started("http", f"{self._host}:{self._port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            if self._logger:
                self._logger.server_stopped()

    async def _run_until_stopped(self) -> None:
        await self.start()

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Expected on shutdown; fall through to stop() in the finally block.
            pass
        finally:
            await self.stop()
