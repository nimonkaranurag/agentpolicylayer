from __future__ import annotations

import functools
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from ..execution import LifecycleExecutor
from ..lifecycle import LifecycleContext
from ..lifecycle.predefined_sequences import (
    LLM_CALL_POST_RESPONSE_SEQUENCE,
    LLM_CALL_PRE_REQUEST_SEQUENCE,
)
from ..messages import get_message_adapter
from .method_patcher import MethodPatcher

if TYPE_CHECKING:
    from ..state import InstrumentationState

WrapperFactory = Callable[[Callable], Callable]


class BaseProvider(ABC):
    def __init__(self, state: InstrumentationState) -> None:
        self.state: InstrumentationState = state
        self.method_patcher: MethodPatcher = MethodPatcher()
        self.message_adapter = get_message_adapter(self.provider_name)
        self.executor: LifecycleExecutor = LifecycleExecutor(state)

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

    # -- Provider-specific request/response shape (overridable) ---------------------

    def extract_messages_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> Any:
        return kwargs.get("messages", [])

    def extract_model_from_request(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> str:
        return kwargs.get("model", "unknown")

    def extract_text_from_response(self, response: Any) -> str:
        try:
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError):
            return ""

    def apply_text_to_response(self, response: Any, new_text: str) -> Any:
        response.choices[0].message.content = new_text
        return response

    def extract_chunk_text(self, chunk: Any) -> str:
        """
        Text carried by one streamed chunk (default: chat-completions delta).
        """
        try:
            return chunk.choices[0].delta.content or ""
        except (AttributeError, IndexError, TypeError):
            return ""

    def apply_chunk_text(self, chunk: Any, new_text: str) -> None:
        """
        Write text back onto a streamed chunk (default: chat-completions delta).
        """
        try:
            chunk.choices[0].delta.content = new_text
        except (AttributeError, IndexError, TypeError):
            pass

    # -- Wrapper factories ---------------------------------------------------------
    #
    # Each factory receives the *captured original* and returns the wrapper, so a wrapper
    # reaches its original by closure rather than by index into a shared list — the index
    # coupling was order-fragile and broke under re-patching.

    def _sync_instance_factory(self) -> WrapperFactory:
        provider = self

        def factory(original: Callable) -> Callable:
            @functools.wraps(original)
            def wrapper(instance_self: Any, *args: Any, **kwargs: Any) -> Any:
                def bound(*a: Any, **kw: Any) -> Any:
                    return original(instance_self, *a, **kw)

                return provider.execute_llm_call_sync(
                    bound, instance_self, *args, **kwargs
                )

            return wrapper

        return factory

    def _async_instance_factory(self) -> WrapperFactory:
        provider = self

        def factory(original: Callable) -> Callable:
            @functools.wraps(original)
            async def wrapper(instance_self: Any, *args: Any, **kwargs: Any) -> Any:
                async def bound(*a: Any, **kw: Any) -> Any:
                    return await original(instance_self, *a, **kw)

                return await provider.execute_llm_call_async(
                    bound, instance_self, *args, **kwargs
                )

            return wrapper

        return factory

    def _sync_module_factory(self) -> WrapperFactory:
        provider = self

        def factory(original: Callable) -> Callable:
            @functools.wraps(original)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return provider.execute_llm_call_sync(original, None, *args, **kwargs)

            return wrapper

        return factory

    def _async_module_factory(self) -> WrapperFactory:
        provider = self

        def factory(original: Callable) -> Callable:
            @functools.wraps(original)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await provider.execute_llm_call_async(
                    original, None, *args, **kwargs
                )

            return wrapper

        return factory

    # -- Lifecycle -----------------------------------------------------------------

    def build_lifecycle_context(
        self, instance: Any, *args: Any, **kwargs: Any
    ) -> LifecycleContext:
        raw_messages = self.extract_messages_from_request(instance, *args, **kwargs)
        apl_messages = self.message_adapter.to_apl_messages(raw_messages)

        return LifecycleContext(
            raw_messages=raw_messages,
            apl_messages=apl_messages,
            model_name=self.extract_model_from_request(instance, *args, **kwargs),
            original_kwargs=dict(kwargs),
            response_text_applier=self.apply_text_to_response,
            # Lets the context convert a request-message MODIFY back to this
            # provider's native shape before it is written to the SDK call.
            message_adapter_to_raw=self.message_adapter.from_apl_messages,
        )

    def write_request_messages(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        raw_messages: Any,
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        Write modified request messages into the slot this SDK reads.

        Default (chat-completions shape): the ``messages=`` keyword. Providers whose SDK
        takes the prompt elsewhere (LangChain's positional ``invoke(input)``) override
        this; mirror :meth:`extract_messages_from_request`.
        """
        new_kwargs = dict(kwargs)
        new_kwargs["messages"] = raw_messages
        return args, new_kwargs

    def _effective_call(
        self,
        context: LifecycleContext,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        The (args, kwargs) to call the original SDK method with after the pre-request
        sequence: any modified request messages routed back to the right slot.
        """
        effective_kwargs = context.get_effective_kwargs()
        if context.request_messages_modified:
            return self.write_request_messages(
                args, effective_kwargs, context.effective_request_messages()
            )
        return args, effective_kwargs

    @staticmethod
    def _is_streaming(kwargs: dict[str, Any]) -> bool:
        return bool(kwargs.get("stream"))

    def execute_llm_call_sync(
        self,
        original_method: Callable,
        instance: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.state.is_inside_policy_evaluation():
            return original_method(*args, **kwargs)

        context: LifecycleContext = self.build_lifecycle_context(
            instance, *args, **kwargs
        )

        self.executor.execute_sequence(LLM_CALL_PRE_REQUEST_SEQUENCE, context)

        call_args, effective_kwargs = self._effective_call(context, args, kwargs)
        response = original_method(*call_args, **effective_kwargs)

        if self._is_streaming(effective_kwargs):
            return self.executor.enforce_sync_stream(
                response,
                LLM_CALL_POST_RESPONSE_SEQUENCE,
                context,
                self.extract_chunk_text,
                self.apply_chunk_text,
            )

        context.response = response
        context.response_text = self.extract_text_from_response(response)
        self.executor.execute_sequence(LLM_CALL_POST_RESPONSE_SEQUENCE, context)
        return context.response

    async def execute_llm_call_async(
        self,
        original_method: Callable,
        instance: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.state.is_inside_policy_evaluation():
            return await original_method(*args, **kwargs)

        context: LifecycleContext = self.build_lifecycle_context(
            instance, *args, **kwargs
        )

        await self.executor.execute_sequence_async(
            LLM_CALL_PRE_REQUEST_SEQUENCE, context
        )

        call_args, effective_kwargs = self._effective_call(context, args, kwargs)
        response = await original_method(*call_args, **effective_kwargs)

        if self._is_streaming(effective_kwargs):
            return await self.executor.enforce_async_stream(
                response,
                LLM_CALL_POST_RESPONSE_SEQUENCE,
                context,
                self.extract_chunk_text,
                self.apply_chunk_text,
            )

        context.response = response
        context.response_text = self.extract_text_from_response(response)
        await self.executor.execute_sequence_async(
            LLM_CALL_POST_RESPONSE_SEQUENCE, context
        )
        return context.response

    # -- Always-streaming entry points (e.g. LangChain .stream()/.astream()) -------
    #
    # Unlike chat-completions create(stream=True), these methods *are* the stream:
    # there is no `stream` kwarg to detect, so they get dedicated wrappers that always
    # run the buffering enforcement path. Without these the helper fell through to the
    # non-streaming branch, ran extract_text on the generator object, and never
    # enforced the output policy on the streamed text.

    def _sync_stream_instance_factory(self) -> WrapperFactory:
        provider = self

        def factory(original: Callable) -> Callable:
            @functools.wraps(original)
            def wrapper(instance_self: Any, *args: Any, **kwargs: Any) -> Any:
                def bound(*a: Any, **kw: Any) -> Any:
                    return original(instance_self, *a, **kw)

                return provider.execute_llm_stream_sync(
                    bound, instance_self, *args, **kwargs
                )

            return wrapper

        return factory

    def _async_stream_instance_factory(self) -> WrapperFactory:
        provider = self

        def factory(original: Callable) -> Callable:
            @functools.wraps(original)
            def wrapper(instance_self: Any, *args: Any, **kwargs: Any) -> Any:
                # `.astream()` must return an async iterator (so `async for` works),
                # not a coroutine — so hand back the async generator directly.
                return provider._astream_enforced(
                    original, instance_self, *args, **kwargs
                )

            return wrapper

        return factory

    def execute_llm_stream_sync(
        self,
        original_method: Callable,
        instance: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.state.is_inside_policy_evaluation():
            return original_method(*args, **kwargs)

        context = self.build_lifecycle_context(instance, *args, **kwargs)
        self.executor.execute_sequence(LLM_CALL_PRE_REQUEST_SEQUENCE, context)
        call_args, effective_kwargs = self._effective_call(context, args, kwargs)
        stream = original_method(*call_args, **effective_kwargs)
        return self.executor.enforce_sync_stream(
            stream,
            LLM_CALL_POST_RESPONSE_SEQUENCE,
            context,
            self.extract_chunk_text,
            self.apply_chunk_text,
        )

    async def _astream_enforced(
        self,
        original_method: Callable,
        instance: Any,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        if self.state.is_inside_policy_evaluation():
            async for chunk in original_method(instance, *args, **kwargs):
                yield chunk
            return

        context = self.build_lifecycle_context(instance, *args, **kwargs)
        await self.executor.execute_sequence_async(
            LLM_CALL_PRE_REQUEST_SEQUENCE, context
        )
        call_args, effective_kwargs = self._effective_call(context, args, kwargs)
        stream = original_method(instance, *call_args, **effective_kwargs)
        enforced = await self.executor.enforce_async_stream(
            stream,
            LLM_CALL_POST_RESPONSE_SEQUENCE,
            context,
            self.extract_chunk_text,
            self.apply_chunk_text,
        )
        async for chunk in enforced:
            yield chunk
