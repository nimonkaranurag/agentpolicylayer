from typing import Dict, Type

from .base_adapter import BaseMessageAdapter
from .chat_completions_adapter import (
    ChatCompletionsMessageAdapter,
)
from .langchain_adapter import LangChainMessageAdapter

MESSAGE_ADAPTER_REGISTRY: Dict[
    str, Type[BaseMessageAdapter]
] = {
    "openai": ChatCompletionsMessageAdapter,
    "anthropic": ChatCompletionsMessageAdapter,
    "litellm": ChatCompletionsMessageAdapter,
    "watsonx": ChatCompletionsMessageAdapter,
    "langchain": LangChainMessageAdapter,
}


def get_message_adapter(
    provider_name: str,
) -> BaseMessageAdapter:
    adapter_class = MESSAGE_ADAPTER_REGISTRY.get(
        provider_name, ChatCompletionsMessageAdapter
    )
    return adapter_class()
