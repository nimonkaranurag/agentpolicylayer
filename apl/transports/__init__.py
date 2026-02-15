from typing import TYPE_CHECKING, Dict, Type

from .base_transport import BaseTransport
from .http import HTTPTransport
from .stdio import StdioTransport

if TYPE_CHECKING:
    from apl.server import PolicyServer

TRANSPORT_REGISTRY: Dict[str, Type[BaseTransport]] = {
    "stdio": StdioTransport,
    "http": HTTPTransport,
}


def create_transport(
    transport_type: str,
    server: "PolicyServer",
    **kwargs,
) -> BaseTransport:
    transport_class = TRANSPORT_REGISTRY.get(transport_type)
    if transport_class is None:
        raise ValueError(
            f"Unknown transport: {transport_type}"
        )
    return transport_class(server, **kwargs)


__all__ = [
    "BaseTransport",
    "StdioTransport",
    "HTTPTransport",
    "TRANSPORT_REGISTRY",
    "create_transport",
]
