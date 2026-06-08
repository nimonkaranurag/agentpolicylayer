from __future__ import annotations

from collections.abc import Callable

from .base_client_transport import BaseClientTransport
from .http_client_transport import HttpClientTransport
from .stdio_client_transport import (
    StdioClientTransport,
)

# Maps URI scheme -> a factory that builds the transport from the URI. The concrete
# transports take their URI positionally (plus keyword-only tuning), so the registry is
# typed as the factory call site uses it rather than as a uniform class type.
TRANSPORT_SCHEME_REGISTRY: dict[str, Callable[[str], BaseClientTransport]] = {
    "stdio": StdioClientTransport,
    "http": HttpClientTransport,
    "https": HttpClientTransport,
}


def resolve_client_transport_for_uri(
    uri: str,
) -> BaseClientTransport:
    scheme: str = uri.split("://")[0]
    transport_factory: Callable[[str], BaseClientTransport] | None = (
        TRANSPORT_SCHEME_REGISTRY.get(scheme)
    )

    if transport_factory is None:
        supported_schemes: str = ", ".join(TRANSPORT_SCHEME_REGISTRY.keys())
        raise ValueError(
            f"Unsupported URI scheme '{scheme}' in '{uri}'. "
            f"Supported schemes: {supported_schemes}"
        )

    return transport_factory(uri)


__all__: list[str] = [
    "BaseClientTransport",
    "StdioClientTransport",
    "HttpClientTransport",
    "TRANSPORT_SCHEME_REGISTRY",
    "resolve_client_transport_for_uri",
]
