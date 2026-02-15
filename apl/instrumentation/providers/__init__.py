from typing import Dict, Type

from .anthropic_provider import AnthropicProvider
from .base_provider import BaseProvider
from .langchain_provider import LangChainProvider
from .litellm_provider import LiteLLMProvider
from .openai_provider import OpenAIProvider
from .watsonx_provider import WatsonXProvider

PROVIDER_REGISTRY: Dict[str, Type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "litellm": LiteLLMProvider,
    "langchain": LangChainProvider,
    "watsonx": WatsonXProvider,
}
