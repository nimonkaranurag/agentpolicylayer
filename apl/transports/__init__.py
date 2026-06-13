from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base_transport import BaseTransport
from .stdio import StdioTransport

if TYPE_CHECKING:
    from apl.server import PolicyServer

_HTTP_EXTRA_HINT = (
    "The HTTP transport requires the 'http' extra: "
    "pip install 'agent-policy-layer[http]'"
)


def create_transport(
    transport_type: str,
    server: "PolicyServer",
    **kwargs: Any,
) -> BaseTransport:
    if transport_type == "stdio":
        return StdioTransport(server, **kwargs)
    if transport_type == "http":
        # Imported lazily so stdio serving (and `import apl`) work without aiohttp;
        # a clear hint is raised when HTTP is requested without the extra.
        try:
            from .http import HTTPTransport
        except ImportError as exc:
            raise ImportError(_HTTP_EXTRA_HINT) from exc
        return HTTPTransport(server, **kwargs)
    raise ValueError(f"Unknown transport: {transport_type}")


def __getattr__(name: str) -> object:
    """
    Lazily expose ``HTTPTransport`` (PEP 562).

    ``from apl.transports import HTTPTransport`` still works, but the aiohttp import is
    deferred until first use rather than fired at package-import time — so the HTTP
    transport's dependency stays off the common import path.
    """
    if name == "HTTPTransport":
        from .http import HTTPTransport

        return HTTPTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseTransport",
    "StdioTransport",
    "HTTPTransport",
    "create_transport",
]
