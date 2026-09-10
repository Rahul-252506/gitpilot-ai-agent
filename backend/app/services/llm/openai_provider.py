"""OpenAI provider — the default practical provider.

Isolated in this module; the rest of the application only knows
``LLMProvider``.
"""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.core.errors import LLMConfigurationError, LLMError
from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolSpec,
)


def _to_openai_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content or "",
                }
            )
        elif msg.role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            out.append(item)
        else:
            out.append({"role": msg.role, "content": msg.content})
    return out


def _to_tool_specs(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, temperature: float = 0.2) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not set. Set it in the environment or switch "
                "LLM_PROVIDER to 'mock' for offline/demo mode."
            )
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._temperature = temperature

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _to_openai_messages(messages),
            "temperature": self._temperature,
        }
        if tools:
            kwargs["tools"] = _to_tool_specs(tools)
        if response_format:
            kwargs["response_format"] = response_format
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # openai raises typed exceptions; keep them out of the API
            raise LLMError(f"LLM request failed: {type(exc).__name__}: {str(exc)[:300]}") from exc

        message = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        if getattr(message, "tool_calls", None):
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=arguments)
                )
        return LLMResponse(content=message.content, tool_calls=tool_calls)