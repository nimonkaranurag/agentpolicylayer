import asyncio
import time

from apl.logging import get_logger
from apl.types import Decision, PolicyEvent, Verdict

from .registered_policy import RegisteredPolicy

logger = get_logger("server")


async def invoke_policy_handler(
    policy: RegisteredPolicy,
    event: PolicyEvent,
) -> Verdict:
    start_time = time.perf_counter()

    try:
        result = policy.handler(event)

        if asyncio.iscoroutine(result):
            timeout_seconds = policy.timeout_ms / 1000
            result = await asyncio.wait_for(
                result, timeout=timeout_seconds
            )

        elapsed_ms = _calculate_elapsed_ms(start_time)
        return _enrich_verdict_with_policy_metadata(
            result, policy, elapsed_ms
        )

    except asyncio.TimeoutError:
        elapsed_ms = _calculate_elapsed_ms(start_time)
        logger.warning(
            f"Policy {policy.name} timed out after {elapsed_ms:.1f}ms"
        )
        return _create_timeout_verdict(policy, elapsed_ms)

    except Exception as e:
        elapsed_ms = _calculate_elapsed_ms(start_time)
        logger.error(
            f"Policy {policy.name} raised exception: {e}"
        )
        return _create_error_verdict(
            policy, elapsed_ms, str(e)
        )


def _calculate_elapsed_ms(start_time: float) -> float:
    return (time.perf_counter() - start_time) * 1000


def _enrich_verdict_with_policy_metadata(
    result: Verdict | object,
    policy: RegisteredPolicy,
    elapsed_ms: float,
) -> Verdict:
    if not isinstance(result, Verdict):
        logger.warning(
            f"Policy {policy.name} returned non-Verdict: {type(result)}"
        )
        return Verdict.allow(
            reasoning="Policy returned invalid type"
        )

    result.policy_name = policy.name
    result.policy_version = policy.version
    result.evaluation_ms = elapsed_ms
    return result


def _create_timeout_verdict(
    policy: RegisteredPolicy, elapsed_ms: float
) -> Verdict:
    return Verdict(
        decision=Decision.ALLOW,
        reasoning=f"Policy timed out after {policy.timeout_ms}ms",
        policy_name=policy.name,
        evaluation_ms=elapsed_ms,
    )


def _create_error_verdict(
    policy: RegisteredPolicy,
    elapsed_ms: float,
    error_message: str,
) -> Verdict:
    return Verdict(
        decision=Decision.ALLOW,
        reasoning=f"Policy error: {error_message}",
        policy_name=policy.name,
        evaluation_ms=elapsed_ms,
    )
