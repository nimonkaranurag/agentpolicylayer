import asyncio
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable

from .checkpoint import PolicyCheckpoint
from .checkpoint_evaluator import CheckpointEvaluator

if TYPE_CHECKING:
    from apl.layer import PolicyLayer


class NodeWrapper:

    def __init__(
        self,
        policy_layer: "PolicyLayer",
        checkpoints: list[PolicyCheckpoint],
    ):
        self._evaluator = CheckpointEvaluator(
            policy_layer
        )
        self._checkpoints = checkpoints

    def wrap(
        self, node_name: str, node_func: Callable
    ) -> Callable:
        @wraps(node_func)
        async def async_wrapped(
            state: Any, config: Any = None
        ) -> Any:
            await self._evaluate_before_checkpoints(
                state, config, node_name
            )

            if asyncio.iscoroutinefunction(node_func):
                result = (
                    await node_func(state, config)
                    if config
                    else await node_func(state)
                )
            else:
                result = (
                    node_func(state, config)
                    if config
                    else node_func(state)
                )

            await self._evaluate_after_checkpoints(
                result or state, config, node_name
            )
            return result

        @wraps(node_func)
        def sync_wrapped(
            state: Any, config: Any = None
        ) -> Any:
            return asyncio.run(
                async_wrapped(state, config)
            )

        if asyncio.iscoroutinefunction(node_func):
            return async_wrapped
        return sync_wrapped

    async def _evaluate_before_checkpoints(
        self, state: Any, config: Any, node_name: str
    ) -> None:
        for checkpoint in self._checkpoints:
            if self._should_evaluate(
                checkpoint, node_name, before=True
            ):
                await self._evaluator.evaluate(
                    checkpoint,
                    state,
                    config,
                    node_name,
                )

    async def _evaluate_after_checkpoints(
        self, state: Any, config: Any, node_name: str
    ) -> None:
        for checkpoint in self._checkpoints:
            if self._should_evaluate(
                checkpoint, node_name, before=False
            ):
                await self._evaluator.evaluate(
                    checkpoint,
                    state,
                    config,
                    node_name,
                )

    def _should_evaluate(
        self,
        checkpoint: PolicyCheckpoint,
        node_name: str,
        before: bool,
    ) -> bool:
        if checkpoint.before_node_execution != before:
            return False
        if checkpoint.node_name is None:
            return True
        return checkpoint.node_name == node_name
