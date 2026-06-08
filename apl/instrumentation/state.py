from __future__ import annotations

import asyncio
import threading
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional

from apl.layer import PolicyLayer
from apl.types import SessionMetadata

if TYPE_CHECKING:
    from .providers.base_provider import BaseProvider

# Reentrancy guard: "are we currently *inside* a policy evaluation". It must be a
# ``ContextVar``, not ``threading.local`` — evaluations hop onto the shared background loop
# (and async callers interleave many on one thread), so a thread-local flag set by one
# evaluation leaks into a sibling, suppressing its instrumentation or corrupting the guard.
# A ContextVar is per-async-task and propagates across the loop boundary, so each logical
# call has its own flag (ENGINEERING_REVIEW §3.8, WP-6).
_IN_POLICY_EVALUATION: ContextVar[bool] = ContextVar(
    "apl_in_policy_evaluation", default=False
)


@dataclass
class InstrumentationState:
    policy_layer: PolicyLayer
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    custom_metadata: dict = field(default_factory=dict)

    active_providers: List[BaseProvider] = field(default_factory=list)

    _background_loop: Optional[asyncio.AbstractEventLoop] = field(
        default=None, repr=False
    )
    _background_thread: Optional[threading.Thread] = field(default=None, repr=False)
    _background_loop_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False
    )

    def __post_init__(self) -> None:
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())

    @property
    def session_metadata(self) -> SessionMetadata:
        # __post_init__ fills session_id when the caller leaves it None, so it is
        # always set by the time this property is read.
        assert self.session_id is not None
        return SessionMetadata(
            session_id=self.session_id,
            user_id=self.user_id,
            custom=self.custom_metadata,
        )

    def register_provider(self, provider: BaseProvider) -> None:
        self.active_providers.append(provider)

    def clear_providers(self) -> None:
        self.active_providers.clear()

    # -- Reentrancy ----------------------------------------------------------------

    def is_inside_policy_evaluation(self) -> bool:
        return _IN_POLICY_EVALUATION.get()

    def mark_policy_evaluation_started(self) -> None:
        _IN_POLICY_EVALUATION.set(True)

    def mark_policy_evaluation_finished(self) -> None:
        _IN_POLICY_EVALUATION.set(False)

    # -- Background event loop ------------------------------------------------------
    #
    # Sync SDK calls still have to drive the async policy layer, so a single daemon loop
    # runs on its own thread and sync code blocks on it via run_coroutine_threadsafe.

    def run_coroutine_in_background_loop(self, coroutine: Any) -> Any:
        loop = self._get_or_create_background_loop()
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result(timeout=30)

    def _get_or_create_background_loop(self) -> asyncio.AbstractEventLoop:
        with self._background_loop_lock:
            needs_new_loop = (
                self._background_loop is None or not self._background_loop.is_running()
            )
            if needs_new_loop:
                ready = threading.Event()
                loop = asyncio.new_event_loop()
                self._background_loop = loop

                def _run(
                    target_loop: asyncio.AbstractEventLoop, started: threading.Event
                ):
                    asyncio.set_event_loop(target_loop)
                    started.set()
                    target_loop.run_forever()

                self._background_thread = threading.Thread(
                    target=_run,
                    args=(loop, ready),
                    daemon=True,
                    name="apl-instrumentation-loop",
                )
                self._background_thread.start()
                ready.wait()
            # Capture under the lock so a concurrent shutdown can't null the field
            # between here and the return; by now it is the still-running loop or the
            # one just created above.
            background_loop = self._background_loop
        assert background_loop is not None
        return background_loop

    def shutdown_background_loop(self) -> None:
        """
        Stop the background loop and join its thread.

        Called from ``uninstrument`` so a removed instrumentation doesn't leave a live
        daemon loop behind. Safe to call when no loop was ever started.
        """
        with self._background_loop_lock:
            loop = self._background_loop
            thread = self._background_thread
            self._background_loop = None
            self._background_thread = None

        if loop is None:
            return

        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5)
        try:
            loop.close()
        except RuntimeError:
            # Loop didn't stop in time (thread join timed out); leave it for the GC.
            pass
