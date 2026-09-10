"""Provider-agnostic LLM abstraction (.freebuff/04_TECH_STACK.md).

The agent orchestrator only depends on these base types. Swapping the LLM
provider is a configuration change, never an architecture change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """A tool exposed to the model (OpenAI-style function schema)."""

    name: str = Field(description="Tool name, e.g. 'get_issue'")
    description: str = Field(description="Human/LLM-readable description")
    parameters: dict[str, Any] = Field(
        description="JSON Schema for the tool arguments", default_factory=dict
    )


class ToolCall(BaseModel):
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Optional provider-specific data that must round-trip with the call
    # (e.g. Gemini 3 thought signatures). Other providers ignore it.
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class LLMResponse(BaseModel):
    """Normalized provider response: optional text plus optional tool calls."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @property
    def wants_tool_call(self) -> bool:
        return len(self.tool_calls) > 0


class LLMProvider(ABC):
    """Interface every concrete provider implements."""

    name: str = "abstract"

    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send the conversation and available tools, return a normalized response.

        Raises LLMError subclasses on configuration or upstream failures.
        """
        raise NotImplementedError