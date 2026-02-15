from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..execution import (
    AsyncLifecycleExecutor,
    SyncLifecycleExecutor,
)
from ..lifecycle import LifecycleContext
from ..lifecycle.predefined_sequences import (
    LLM_CALL_POST_RESPONSE_SEQUENCE,
    LLM_CALL_PRE_REQUEST_SEQUENCE,
)
from ..messages import get_message_adapter
from .method_patcher import MethodPatcher

if TYPE_CHECKING:
    from ..state import InstrumentationState


class BaseProvider(ABC):

    def __init__(self, state: InstrumentationState) -> None:
        self.state: InstrumentationState = state
        self.method_patcher: MethodPatcher = MethodPatcher()
        self.message_adapter = get_message_adapter(
            self.provider_name
        )
        self.sync_executor: SyncLifecycleExecutor = (
            SyncLifecycleExecutor(state)
        )
        self.async_executor: AsyncLifecycleExecutor = (
            AsyncLifecycleExecutor(state)
        )

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @staticmethod
    @abstractmethod
    def is_available() -> bool: ...

    @abstractmethod
    def patch_all_methods(self) -> None: ...

    def unpatch_all_methods(self) -> None:
        self.method_patcher.remove_all_patches()

    def extract_messages_from_request(
        self, *args: Any, **kwargs: Any
    ) -> Any:
        return kwargs.get("messages", [])

    def extract_model_from_request(
        self, *args: Any, **kwargs: Any
    ) -> str:
        return kwargs.get("model", "unknown")

    def extract_text_from_response(
        self, response: Any
    ) -> str:
        try:
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError):
            return ""

    def apply_text_to_response(
        self, response: Any, new_text: str
    ) -> Any:
        response.choices[0].message.content = new_text
        return response

    def _create_instance_method_sync_wrapper(
        self, patch_target_index: int = 0
    ) -> Any:
        provider: BaseProvider = self

        def wrapper(
            instance_self: Any, *args: Any, **kwargs: Any
        ) -> Any:
            original = (
                provider.method_patcher.patch_targets[
                    patch_target_index
                ].original_method
            )
            bound_method = lambda *a, **kw: original(
                instance_self, *a, **kw
            )
            return provider.execute_llm_call_sync(
                bound_method, *args, **kwargs
            )

        return wrapper

    def _create_instance_method_async_wrapper(
        self, patch_target_index: int = 1
    ) -> Any:
        provider: BaseProvider = self

        async def wrapper(
            instance_self: Any, *args: Any, **kwargs: Any
        ) -> Any:
            original = (
                provider.method_patcher.patch_targets[
                    patch_target_index
                ].original_method
            )

            async def bound_method(
                *a: Any, **kw: Any
            ) -> Any:
                return await original(
                    instance_self, *a, **kw
                )

            return await provider.execute_llm_call_async(
                bound_method, *args, **kwargs
            )

        return wrapper

    def build_lifecycle_context(
        self, *args: Any, **kwargs: Any
    ) -> LifecycleContext:
        raw_messages = self.extract_messages_from_request(
            *args, **kwargs
        )
        apl_messages = self.message_adapter.to_apl_messages(
            raw_messages
        )

        return LifecycleContext(
            raw_messages=raw_messages,
            apl_messages=apl_messages,
            model_name=self.extract_model_from_request(
                *args, **kwargs
            ),
            original_kwargs=dict(kwargs),
            response_text_applier=self.apply_text_to_response,
        )

    def execute_llm_call_sync(
        self,
        original_method: callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.state.is_inside_policy_evaluation():
            return original_method(*args, **kwargs)

        context: LifecycleContext = (
            self.build_lifecycle_context(*args, **kwargs)
        )

        self.sync_executor.execute_sequence(
            LLM_CALL_PRE_REQUEST_SEQUENCE, context
        )

        effective_kwargs: dict[str, Any] = (
            context.get_effective_kwargs()
        )
        context.response = original_method(
            *args, **effective_kwargs
        )
        context.response_text = (
            self.extract_text_from_response(
                context.response
            )
        )

        self.sync_executor.execute_sequence(
            LLM_CALL_POST_RESPONSE_SEQUENCE, context
        )

        return context.response

    async def execute_llm_call_async(
        self,
        original_method: callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.state.is_inside_policy_evaluation():
            return await original_method(*args, **kwargs)

        context: LifecycleContext = (
            self.build_lifecycle_context(*args, **kwargs)
        )

        await self.async_executor.execute_sequence(
            LLM_CALL_PRE_REQUEST_SEQUENCE, context
        )

        effective_kwargs: dict[str, Any] = (
            context.get_effective_kwargs()
        )
        context.response = await original_method(
            *args, **effective_kwargs
        )
        context.response_text = (
            self.extract_text_from_response(
                context.response
            )
        )

        await self.async_executor.execute_sequence(
            LLM_CALL_POST_RESPONSE_SEQUENCE, context
        )

        return context.response
