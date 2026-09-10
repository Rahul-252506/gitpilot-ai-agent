"""Demo provider — deterministic fixture for the Week 3 product demo.

``LLM_PROVIDER=demo`` selects this provider. It performs NO LLM API call
whatsoever: the *investigation* is real (the agent loop, the GitHub tools,
persistence, events, approvals and safety limits all run exactly as in
production), but the model turns are produced by a deterministic state
machine that inspects the real tool outputs already in context:

    1. get_issue                       (real GitHub call)
    2. search_repository               (real GitHub call)
    3. get_file on the first match     (real GitHub call)
    4. final structured fixture report built FROM the actual tool outputs

Nothing is faked or attributed to Gemini: the report is the same
``ResolutionReport`` schema the live agent produces, its evidence items are
verbatim quotes from real tool output, and its warnings state explicitly
that Demo Mode used no live LLM. The real providers (gemini/openai) and the
scriptable mock are unchanged; switching back is one env var.

The class also accepts the same script protocol as ``MockLLMProvider`` so
tests can drive deterministic scenarios.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.llm.base import LLMMessage, LLMResponse, ToolSpec
from app.services.llm.mock_provider import (
    MockExhaustedError,
    MockLLMProvider,
    _find_task,
    _has_get_issue_result,
    tool_call_response,
)

_DEMO_WARNING = (
    "DEMO MODE: this report was produced by GitPilot's deterministic demo "
    "fixture (LLM_PROVIDER=demo), not by a live Gemini API call. The agent "
    "loop, GitHub tools, execution timeline, persistence and approval "
    "safety are the real production pipeline; only the model reasoning "
    "step is replaced."
)

_DEMO_WARNING_2 = (
    "Evidence items below are verbatim excerpts from real GitHub tool "
    "output gathered during this run. No LLM reasoning was applied to them; "
    "in a live run (LLM_PROVIDER=gemini) the model would produce the root "
    "cause, resolution steps and test plan from this same evidence."
)


def _keyword_from_issue(issue_text: str) -> str:
    """Pick a deterministic search keyword from the real issue text."""
    haystack = issue_text.lower()
    for word in ("login", "auth", "crash", "email", "token", "timeout", "error"):
        if word in haystack:
            return word
    title = re.search(r"Title:\s*(.+)", issue_text)
    if title:
        for word in re.findall(r"[a-zA-Z]{4,}", title.group(1)):
            return word.lower()
    return "issue"


def _first_match_path(search_text: str) -> str | None:
    """First *code* file listed in a real search_repository tool result.

    Prefers source files (e.g. .py/.js/.ts) over docs like README so the
    demo inspects the most relevant evidence; every candidate still comes
    verbatim from the real search output."""
    paths = []
    for line in search_text.splitlines():
        match = re.match(r"-\s+(\S+\.\w+)", line.strip())
        if match:
            paths.append(match.group(1))
    if not paths:
        return None
    docs = ("readme", "license", "contributing")
    code = [p for p in paths if not any(d in p.lower() for d in docs)]
    return (code or paths)[0]


def _snippet_from_file(file_text: str) -> str:
    """Short verbatim excerpt from a real get_file tool result."""
    body = file_text.split("\n", 1)[1] if "\n" in file_text else file_text
    for line in body.splitlines():
        stripped = line.strip()
        if any(term in stripped.lower() for term in ("email", "login", "password", "auth")):
            return stripped[:160]
    for line in body.splitlines():
        if line.strip():
            return line.strip()[:160]
    return "(empty file)"


class DemoLLMProvider(MockLLMProvider):
    """Deterministic demo stand-in for the model. See module docstring."""

    name = "demo"

    def _default_strategy(
        self, messages: list[LLMMessage], tools: list[ToolSpec]
    ) -> LLMResponse:
        # 1. Retrieve the real issue first (same contract as the mock).
        if not _has_get_issue_result(messages):
            task = _find_task(messages)
            if task is None:
                raise MockExhaustedError(
                    "Demo provider could not locate the repository/issue in the task."
                )
            repository, number = task
            owner, _, repo = repository.partition("/")
            return tool_call_response(
                "get_issue",
                {"owner": owner or repository, "repo": repo or repository, "issue_number": number},
                call_id="demo_call_1",
            )

        issue_text = self._latest_tool_text(messages, marker="Issue #")
        search_text = self._latest_tool_text(messages, marker="Matches for")
        file_text = self._latest_tool_text(messages, marker="File:")

        # 2. Search the repository using a keyword from the real issue.
        if search_text is None:
            keyword = _keyword_from_issue(issue_text or "")
            task = _find_task(messages) or ("", 0)
            owner, _, repo = task[0].partition("/")
            return tool_call_response(
                "search_repository",
                {"owner": owner or task[0], "repo": repo or task[0], "query": keyword},
                call_id="demo_call_2",
            )

        # 3. Inspect the first file the real search returned.
        if file_text is None:
            path = _first_match_path(search_text)
            if path:
                task = _find_task(messages) or ("", 0)
                owner, _, repo = task[0].partition("/")
                return tool_call_response(
                    "get_file",
                    {"owner": owner or task[0], "repo": repo or task[0], "path": path},
                    call_id="demo_call_3",
                )

        # 4. Final fixture report built from the actual tool outputs.
        return self._fixture_report(issue_text, file_text)

    # ---------------- helpers ----------------
    @staticmethod
    def _latest_tool_text(messages: list[LLMMessage], marker: str) -> str | None:
        for msg in reversed(messages):
            if msg.role == "tool" and msg.content and marker in msg.content:
                return msg.content
        return None

    def _fixture_report(self, issue_text: str | None, file_text: str | None) -> LLMResponse:
        title = "Issue"
        body_excerpt = ""
        if issue_text:
            title_match = re.search(r"Title:\s*(.+)", issue_text)
            title = title_match.group(1).strip() if title_match else title
            body_match = re.search(r"Body:\n(.*?)(?:\nRecent comments|\Z)", issue_text, re.DOTALL)
            body_excerpt = (body_match.group(1).strip() if body_match else "")[:200]

        evidence: list[dict[str, str]] = []
        affected_files: list[str] = []
        if issue_text:
            evidence.append(
                {
                    "source": "get_issue",
                    "quote": body_excerpt or f"Title: {title}",
                    "kind": "confirmed",
                }
            )
        if file_text:
            first_line = file_text.splitlines()[0] if file_text else ""
            path = first_line.replace("File:", "").strip().split(" ")[0] if first_line else "file"
            affected_files.append(path)
            evidence.append(
                {
                    "source": f"get_file:{path}",
                    "quote": _snippet_from_file(file_text),
                    "kind": "confirmed",
                }
            )

        report: dict[str, Any] = {
            "issue_summary": f"{title}." + (f" {body_excerpt}" if body_excerpt else ""),
            "category": "unknown",
            "priority": "unknown",
            "root_cause": (
                "Not determined by model reasoning: Demo Mode performs no LLM "
                "call. The evidence above was gathered by the real agent "
                "pipeline from GitHub; a live Gemini run would state the root "
                "cause here based on exactly this evidence."
            ),
            "evidence": evidence,
            "affected_files": affected_files,
            "resolution_steps": [
                "Demo Mode fixture: the live model (LLM_PROVIDER=gemini) "
                "generates concrete resolution steps from the gathered "
                "evidence in this slot."
            ],
            "test_plan": [
                "Demo Mode fixture: the live model proposes a test plan in "
                "this slot."
            ],
            "confidence": 0.2,
            "warnings": [_DEMO_WARNING, _DEMO_WARNING_2],
            "proposed_actions": [],
        }
        return LLMResponse(content=json.dumps(report))
