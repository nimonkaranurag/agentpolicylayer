from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional

from apl.layer import PolicyLayer
from apl.types import SessionMetadata

if TYPE_CHECKING:
    from .providers.base_provider import BaseProvider


@dataclass
class InstrumentationState:
    policy_layer: PolicyLayer
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    custom_metadata: dict = field(default_factory=dict)

    active_providers: List[BaseProvider] = field(
        default_factory=list
    )

    _reentrancy_flag: threading.local = field(
        default_factory=threading.local, repr=False
    )
    _background_loop: Optional[
        asyncio.AbstractEventLoop
    ] = field(default=None, repr=False)
    _background_loop_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False
    )

    def __post_init__(self):
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())

    @property
    def session_metadata(self) -> SessionMetadata:
        return SessionMetadata(
            session_id=self.session_id,
            user_id=self.user_id,
            custom=self.custom_metadata,
        )

    def register_provider(
        self, provider: BaseProvider
    ) -> None:
        self.active_providers.append(provider)

    def clear_providers(self) -> None:
        self.active_providers.clear()

    def is_inside_policy_evaluation(self) -> bool:
        return getattr(
            self._reentrancy_flag, "active", False
        )

    def mark_policy_evaluation_started(self) -> None:
        self._reentrancy_flag.active = True

    def mark_policy_evaluation_finished(self) -> None:
        self._reentrancy_flag.active = False

    def run_coroutine_in_background_loop(
        self, coroutine
    ) -> Any:
        loop = self._get_or_create_background_loop()
        future = asyncio.run_coroutine_threadsafe(
            coroutine, loop
        )
        return future.result(timeout=30)

    def _get_or_create_background_loop(
        self,
    ) -> asyncio.AbstractEventLoop:
        with self._background_loop_lock:
            needs_new_loop = (
                self._background_loop is None
                or not self._background_loop.is_running()
            )
            if needs_new_loop:
                ready = threading.Event()
                self._background_loop = (
                    asyncio.new_event_loop()
                )
                loop = self._background_loop

                def _run(l, r):
                    asyncio.set_event_loop(l)
                    r.set()
                    l.run_forever()

                loop_thread = threading.Thread(
                    target=_run,
                    args=(loop, ready),
                    daemon=True,
                    name="apl-instrumentation-loop",
                )
                loop_thread.start()
                ready.wait()
        return self._background_loop
