import asyncio
from typing import TYPE_CHECKING

from aiohttp import web

from apl.logging import APLLogger, get_logger, setup_logging
from apl.transports.base_transport import BaseTransport
from apl.utilities import kill_process_on_port

from .app_factory import create_http_application

if TYPE_CHECKING:
    from apl.server import PolicyServer

logger = get_logger("transport.http")


class HTTPTransport(BaseTransport):
    def __init__(
        self,
        server: "PolicyServer",
        host: str = "0.0.0.0",
        port: int = 8080,
        apl_logger: APLLogger | None = None,
    ):
        super().__init__(server)
        self._host = host
        self._port = port
        self._logger = apl_logger
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def run(self) -> None:
        asyncio.run(self._run_until_stopped())

    async def start(self) -> None:
        if self._logger is None:
            self._logger = setup_logging()

        app = create_http_application(self.server, self._logger)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self._host, self._port)

        try:
            await self._site.start()
        except OSError as e:
            if e.errno in (48, 98):
                await self._handle_port_in_use()
            else:
                raise

        self._logger.server_started("http", f"{self._host}:{self._port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._logger.server_stopped()

    async def _run_until_stopped(self) -> None:
        await self.start()

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def _handle_port_in_use(self) -> None:
        logger.warning(f"Port {self._port} in use, attempting to free it...")

        if kill_process_on_port(self._port):
            await asyncio.sleep(0.5)
            try:
                await self._site.start()
            except OSError:
                logger.error(
                    f"Could not bind to port {self._port} "
                    "even after killing existing process"
                )
                raise
        else:
            raise OSError(f"Could not free port {self._port}")
