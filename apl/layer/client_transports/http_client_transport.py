from __future__ import annotations

import logging
from typing import Any

from .base_client_transport import BaseClientTransport

logger: logging.Logger = logging.getLogger("apl")

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
        manifest_url: str = f"{self._base_url}/manifest"

        async with self._session.get(
            manifest_url
        ) as response:
            if response.status != 200:
                raise ConnectionError(
                    f"Failed to connect to {self._base_url}: HTTP {response.status}"
                )
            manifest_data: dict[str, Any] = (
                await response.json()
            )
            return manifest_data

    async def evaluate(
        self, serialized_event: dict
    ) -> list[dict]:
        if self._session is None:
            return []

        evaluate_url: str = f"{self._base_url}/evaluate"

        async with self._session.post(
            evaluate_url, json=serialized_event
        ) as response:
            if response.status != 200:
                logger.error(
                    f"Policy evaluation failed: HTTP {response.status}"
                )
                return []

            data: dict[str, Any] = await response.json()
            return data.get("verdicts", [])

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
