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
    *,
    token: str | None = None,
) -> BaseClientTransport:
    scheme: str = uri.split("://")[0]

    if scheme not in TRANSPORT_SCHEME_REGISTRY:
        supported_schemes: str = ", ".join(TRANSPORT_SCHEME_REGISTRY.keys())
        raise ValueError(
            f"Unsupported URI scheme '{scheme}' in '{uri}'. "
            f"Supported schemes: {supported_schemes}"
        )

    if scheme in ("http", "https"):
        return HttpClientTransport(uri, token=token)
    # stdio: a bearer token is not part of the stdio protocol, so it's ignored.
    return StdioClientTransport(uri)


__all__: list[str] = [
    "BaseClientTransport",
    "StdioClientTransport",
    "HttpClientTransport",
    "TRANSPORT_SCHEME_REGISTRY",
    "resolve_client_transport_for_uri",
]
