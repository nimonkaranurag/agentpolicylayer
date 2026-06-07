from __future__ import annotations

import asyncio
from typing import Any

from apl.types import PolicyUnavailableError

from .base_client_transport import BaseClientTransport

try:
    import aiohttp

    HAS_AIOHTTP: bool = True
except ImportError:
    HAS_AIOHTTP = False

# A bounded default keeps the agent's hot path from blocking on aiohttp's 5-minute
# default. Every availability failure (timeout, non-200, network error) raises
# PolicyUnavailableError so the client can fail closed.
DEFAULT_TIMEOUT_SECONDS: float = 10.0


class HttpClientTransport(BaseClientTransport):
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url: str = base_url.rstrip("/")
        self._timeout_seconds: float = timeout_seconds
        self._session: aiohttp.ClientSession | None = None
        # aiohttp pins a ClientSession to the loop it was created on. We track
        # that loop so evaluate() can recreate the session if it ends up running
        # on a different loop (eager connect() elsewhere, or the LangGraph sync
        # bridge) instead of crashing with "Event loop is closed".
        self._session_loop: asyncio.AbstractEventLoop | None = None

    def _new_session(self) -> aiohttp.ClientSession:
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self._session_loop = asyncio.get_running_loop()
        return self._session

    def _session_for_current_loop(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise PolicyUnavailableError(
                f"HTTP transport for {self._base_url} is not connected"
            )
        loop_changed = (
            self._session_loop is not None
            and self._session_loop is not asyncio.get_running_loop()
        )
        if loop_changed or getattr(self._session, "closed", False):
            # Session was created on a different (or now-closed) loop; aiohttp
            # can't be used across loops, so recreate it here. The stale session
            # is abandoned — it can't be awaited-closed from this loop.
            return self._new_session()
        return self._session

    async def connect(self) -> dict | None:
        if not HAS_AIOHTTP:
            raise ImportError(
                "aiohttp is required for HTTP transport. "
                "Install it with: pip install aiohttp"
            )

        session = self._new_session()

        manifest_url: str = f"{self._base_url}/manifest"
        try:
            async with session.get(manifest_url) as response:
                if response.status != 200:
                    raise PolicyUnavailableError(
                        f"policy server {self._base_url} returned HTTP "
                        f"{response.status} on connect"
                    )
                manifest_data: dict[str, Any] = await response.json()
                return manifest_data
        except PolicyUnavailableError:
            await self._close_session()
            raise
        except Exception as exc:
            # Unreachable host, timeout, malformed manifest body — all are
            # availability failures the caller must turn into a deny.
            await self._close_session()
            raise PolicyUnavailableError(
                f"could not connect to policy server {self._base_url}: {exc}"
            ) from exc

    async def evaluate(self, serialized_event: dict) -> list[dict]:
        session = self._session_for_current_loop()

        evaluate_url: str = f"{self._base_url}/evaluate"

        try:
            async with session.post(evaluate_url, json=serialized_event) as response:
                if response.status != 200:
                    raise PolicyUnavailableError(
                        f"policy server {self._base_url} returned HTTP "
                        f"{response.status}"
                    )

                data: dict[str, Any] = await response.json()
                return data.get("verdicts", [])
        except PolicyUnavailableError:
            raise
        except Exception as exc:
            # Any failure to obtain verdicts (timeout, network error, malformed
            # body, …) is an availability failure; surface it so the caller can
            # fail closed instead of silently allowing the action.
            raise PolicyUnavailableError(
                f"HTTP transport error talking to {self._base_url}: {exc}"
            ) from exc

    async def close(self) -> None:
        await self._close_session()

    async def _close_session(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
