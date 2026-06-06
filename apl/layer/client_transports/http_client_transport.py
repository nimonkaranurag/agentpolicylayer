from __future__ import annotations

from typing import Any

from apl.types import PolicyUnavailableError

from .base_client_transport import BaseClientTransport

try:
    import aiohttp

    HAS_AIOHTTP: bool = True
except ImportError:
    HAS_AIOHTTP = False


class HttpClientTransport(BaseClientTransport):

    def __init__(self, base_url: str) -> None:
        self._base_url: str = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> dict | None:
        if not HAS_AIOHTTP:
            raise ImportError(
                "aiohttp is required for HTTP transport. "
                "Install it with: pip install aiohttp"
            )

        self._session = aiohttp.ClientSession()
        try:
            manifest_url: str = f"{self._base_url}/manifest"
            async with self._session.get(manifest_url) as response:
                if response.status != 200:
                    raise ConnectionError(
                        f"Failed to connect to {self._base_url}: HTTP {response.status}"
                    )
                manifest_data: dict[str, Any] = await response.json()
                return manifest_data
        except Exception:
            await self._session.close()
            self._session = None
            raise

    async def evaluate(self, serialized_event: dict) -> list[dict]:
        if self._session is None:
            raise PolicyUnavailableError(
                f"HTTP transport for {self._base_url} is not connected"
            )

        evaluate_url: str = f"{self._base_url}/evaluate"

        try:
            async with self._session.post(
                evaluate_url, json=serialized_event
            ) as response:
                if response.status != 200:
                    raise PolicyUnavailableError(
                        f"Policy server {self._base_url} returned HTTP "
                        f"{response.status}"
                    )

                data: dict[str, Any] = await response.json()
                return data.get("verdicts", [])
        except PolicyUnavailableError:
            raise
        except Exception as exc:
            # Any failure to obtain verdicts (network error, malformed body, …)
            # is an availability failure; surface it so the caller can fail
            # closed instead of silently allowing the action.
            raise PolicyUnavailableError(
                f"HTTP transport error talking to {self._base_url}: {exc}"
            ) from exc

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
