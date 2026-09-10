"""Deterministic mock LLM provider.

Used by tests (scriptable) and as an offline/demo provider when no API key
is configured.

Default behavior (no script): a minimal honest investigation —
1. call `get_issue` with the repository/issue from the task,
2. then produce a structured report whose facts come only from the issue
   text actually retrieved, with warnings making clear that this is a
   deterministic demo provider that does not reason or search code.

When a script is supplied, each ``complete`` call pops the next response
from the script (``LLMResponse`` objects or callables). An exhausted script
falls back to the default strategy so agent runs terminate cleanly.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.core.errors import LLMError
from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolSpec,
)

ScriptItem = LLMResponse | Callable[[list[LLMMessage], list[ToolSpec]], LLMResponse]


def tool_call_response(name: str, arguments: dict[str, Any], call_id: str = "call_mock_1") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def final_response(report: dict[str, Any]) -> LLMResponse:
    return LLMResponse(content=json.dumps(report))


def repeat_tool_call(name: str, arguments: dict[str, Any], times: int = 1000) -> list[LLMResponse]:
    """A script that requests the same tool call repeatedly (for limit tests)."""
    return [
        tool_call_response(name, arguments, call_id=f"call_repeat_{i}")
        for i in range(times)
    ]


class MockExhaustedError(LLMError):
    code = "mock_provider_exhausted"


_TASK_RE = re.compile(r"Repository:\s*(\S+)\s*\nIssue number:\s*(\d+)")


def _find_task(messages: list[LLMMessage]) -> tuple[str, int] | None:
    for msg in messages:
        if msg.role == "user" and msg.content:
            match = _TASK_RE.search(msg.content)
            if match:
                try:
                    return match.group(1), int(match.group(2))
                except ValueError:
                    return None
    return None


def _has_get_issue_result(messages: list[LLMMessage]) -> bool:
    return any(
        msg.role == "tool" and msg.content and "Issue #" in msg.content
        for msg in messages
    )


def _extract_issue_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    title = re.search(r"Title:\s*(.+)", content)
    if title:
        fields["title"] = title.group(1).strip()
    labels = re.search(r"Labels:\s*(.+)", content)
    if labels:
        fields["labels"] = labels.group(1).strip()
    state = re.search(r"Issue #\d+ \((\w+)\)", content)
    if state:
        fields["state"] = state.group(1)
    body = ""
    body_match = re.search(r"Body:\n(.*?)(?:\nRecent comments|\Z)", content, re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()
    fields["body"] = body
    return fields


class MockLLMProvider(LLMProvider):
    name = "mock"

    def __init__(self, script: list[ScriptItem] | None = None) -> None:
        self._script: list[ScriptItem] = list(script or [])
        self.call_count = 0
        self.requested_messages: list[list[LLMMessage]] = []
        self.requested_tools: list[list[ToolSpec]] = []

    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.requested_messages.append(list(messages))
        self.requested_tools.append(list(tools))
        if self._script:
            item = self._script.pop(0)
            if callable(item):
                return item(messages, tools)
            return item
        return self._default_strategy(messages, tools)

    # ---------------- default strategy (offline demo mode) ----------------
    def _default_strategy(
        self, messages: list[LLMMessage], tools: list[ToolSpec]
    ) -> LLMResponse:
        # 1. Retrieve the issue first (mirrors the required agent behavior).
        if not _has_get_issue_result(messages):
            task = _find_task(messages)
            if task is None:
                # No task identity available — cannot proceed meaningfully.
                raise MockExhaustedError(
                    "Mock provider could not locate the repository/issue in the task."
                )
            repository, number = task
            owner, _, repo = repository.partition("/")
            return tool_call_response(
                "get_issue",
                {
                    "owner": owner or repository,
                    "repo": repo or repository,
                    "issue_number": number,
                },
                call_id="call_default_get_issue",
            )

        # 2. Produce an honest report from the issue text actually retrieved.
        issue_text = ""
        for msg in reversed(messages):
            if msg.role == "tool" and msg.content and "Issue #" in msg.content:
                issue_text = msg.content
                break
        fields = _extract_issue_fields(issue_text)
        title = fields.get("title", "(unknown title)")
        body = fields.get("body", "")
        body_excerpt = body[:400]
        report: dict[str, Any] = {
            "issue_summary": f"{title}." + (f" {body_excerpt[:300]}" if body_excerpt else ""),
            "category": "unknown",
            "priority": "unknown",
            "root_cause": (
                "Not determined. The deterministic demo provider does not search "
                "code or reason; it only reports what it observed in the issue."
            ),
            "evidence": [
                {
                    "source": "get_issue",
                    "quote": body_excerpt[:200] or f"Title: {title}",
                    "kind": "confirmed",
                }
            ],
            "affected_files": [],
            "resolution_steps": [
                "Run with LLM_PROVIDER=openai and an OPENAI_API_KEY so the agent can "
                "search the repository and produce a full resolution plan."
            ],
            "test_plan": [],
            "confidence": 0.15,
            "warnings": [
                "LLM_PROVIDER=mock is a deterministic demo provider: it retrieved the "
                "issue but performed no repository search, reasoning, or code inspection. "
                "Configure LLM_PROVIDER=openai with OPENAI_API_KEY for full analysis.",
            ],
        }
        return final_response(report)