"""LLM provider selection and factory."""
from __future__ import annotations

from app.core.config import Settings
from app.core.errors import LLMConfigurationError
from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolSpec,
)
from app.services.llm.mock_provider import (
    MockLLMProvider,
    final_response,
    tool_call_response,
)
from app.services.llm.gemini_provider import GeminiLLMProvider
from app.services.llm.openai_provider import OpenAILLMProvider

__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "ToolCall",
    "ToolSpec",
    "OpenAILLMProvider",
    "GeminiLLMProvider",
    "MockLLMProvider",
    "final_response",
    "tool_call_response",
    "get_llm_provider",
]


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Create the provider configured via ``LLM_PROVIDER`` env var."""
    provider_name = settings.llm_provider.lower()
    if provider_name == "mock":
        return MockLLMProvider()
    if provider_name == "openai":
        return OpenAILLMProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=settings.llm_temperature,
        )
    if provider_name == "gemini":
        return GeminiLLMProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.llm_temperature,
        )
    raise LLMConfigurationError(
        f"Unknown LLM_PROVIDER {provider_name!r}. Use 'gemini', 'openai' or 'mock'."
    )