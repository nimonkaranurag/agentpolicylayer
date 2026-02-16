from __future__ import annotations

from .base_client_transport import BaseClientTransport
from .http_client_transport import HttpClientTransport
from .stdio_client_transport import (
    StdioClientTransport,
)

TRANSPORT_SCHEME_REGISTRY: dict[
    str, type[BaseClientTransport]
] = {
    "stdio": StdioClientTransport,
    "http": HttpClientTransport,
    "https": HttpClientTransport,
}


def resolve_client_transport_for_uri(
    uri: str,
) -> BaseClientTransport:
    scheme: str = uri.split("://")[0]
    transport_class: (
        type[BaseClientTransport] | None
    ) = TRANSPORT_SCHEME_REGISTRY.get(scheme)

    if transport_class is None:
        supported_schemes: str = ", ".join(
            TRANSPORT_SCHEME_REGISTRY.keys()
        )
        raise ValueError(
            f"Unsupported URI scheme '{scheme}' in '{uri}'. "
            f"Supported schemes: {supported_schemes}"
        )

    return transport_class(uri)


__all__: list[str] = [
    "BaseClientTransport",
    "StdioClientTransport",
    "HttpClientTransport",
    "TRANSPORT_SCHEME_REGISTRY",
    "resolve_client_transport_for_uri",
]
