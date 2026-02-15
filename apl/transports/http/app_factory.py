from typing import TYPE_CHECKING

from aiohttp import web

from apl.logging import APLLogger
from apl.metrics import ServerMetrics

from .middleware import MIDDLEWARE_STACK
from .routes import register_all_routes

if TYPE_CHECKING:
    from apl.server import PolicyServer


def create_http_application(
    server: "PolicyServer",
    logger: APLLogger | None = None,
) -> web.Application:
    app = web.Application(middlewares=MIDDLEWARE_STACK)

    app["server"] = server
    app["metrics"] = ServerMetrics()

    if logger:
        app["logger"] = logger

    register_all_routes(app)

    return app
