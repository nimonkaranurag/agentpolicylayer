from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from apl.logging import get_logger
from apl.types import FailMode, PolicyEvent, Verdict

from .registered_policy import RegisteredPolicy

logger = get_logger("server")


async def invoke_policy_handler(
    policy: RegisteredPolicy,
    event: PolicyEvent,
    fail_mode: FailMode = FailMode.CLOSED,
) -> Verdict:
    """
    Run a single policy handler and return its verdict.

    Every failure mode — timeout, exception, or a handler that returns something other
    than a :class:`Verdict` — is resolved through ``fail_mode`` (deny by default) rather
    than silently allowing the action.
    """
    start_time: float = time.perf_counter()
    timeout_seconds: float = policy.timeout_ms / 1000

    try:
        result: Any = await asyncio.wait_for(
            _call_handler(policy.handler, event),
            timeout=timeout_seconds,
        )
        elapsed_ms: float = _calculate_elapsed_ms(start_time)
        return _enrich_verdict_with_policy_metadata(
            result, policy, elapsed_ms, fail_mode
        )

    except asyncio.TimeoutError:
        elapsed_ms = _calculate_elapsed_ms(start_time)
        logger.warning(f"Policy {policy.name} timed out after {elapsed_ms:.1f}ms")
        return _create_unavailable_verdict(
            policy,
            elapsed_ms,
            fail_mode,
            reason=f"Policy timed out after {policy.timeout_ms}ms",
        )

    except Exception as exc:
        elapsed_ms = _calculate_elapsed_ms(start_time)
        logger.error(f"Policy {policy.name} raised exception: {exc}")
        return _create_unavailable_verdict(
            policy,
            elapsed_ms,
            fail_mode,
            reason=f"Policy error: {exc}",
        )


async def _call_handler(handler: Callable, event: PolicyEvent) -> Any:
    """
    Invoke a policy handler so that both async and sync handlers are subject to the same
    timeout.

    Async handlers are awaited directly. Sync handlers are run off the event loop via a
    worker thread; this keeps a slow or hung sync handler from blocking the server loop
    and lets ``asyncio.wait_for`` time it out. (A timed-out thread cannot be killed and
    runs to completion in the background, but the caller has already received its fail-
    closed verdict.)
    """
    if asyncio.iscoroutinefunction(handler):
        return await handler(event)

    result = await asyncio.to_thread(handler, event)
    if asyncio.iscoroutine(result):
        # Defensive: a sync callable that returns a coroutine (e.g. a partial).
        return await result
    return result


def _calculate_elapsed_ms(start_time: float) -> float:
    return (time.perf_counter() - start_time) * 1000


def _enrich_verdict_with_policy_metadata(
    result: Verdict | object,
    policy: RegisteredPolicy,
    elapsed_ms: float,
    fail_mode: FailMode,
) -> Verdict:
    if not isinstance(result, Verdict):
        logger.warning(f"Policy {policy.name} returned non-Verdict: {type(result)}")
        return _create_unavailable_verdict(
            policy,
            elapsed_ms,
            fail_mode,
            reason=f"Policy returned invalid type: {type(result).__name__}",
        )

    result.policy_name = policy.name
    result.policy_version = policy.version
    result.evaluation_ms = elapsed_ms
    return result


def _create_unavailable_verdict(
    policy: RegisteredPolicy,
    elapsed_ms: float,
    fail_mode: FailMode,
    reason: str,
) -> Verdict:
    return Verdict.unavailable(
        fail_mode,
        reasoning=reason,
        policy_name=policy.name,
        evaluation_ms=elapsed_ms,
    )
