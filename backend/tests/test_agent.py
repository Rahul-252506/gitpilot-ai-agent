"""Agent orchestrator tests (.freebuff/14_TESTING_AND_VALIDATION.md).

Uses the scriptable MockLLMProvider so each scenario is deterministic:
normal investigation, issue not found, empty search, rate limit, tool
failure recovery, structured-output retry, step limit, write approval,
LLM failure, and context-driven tool selection (proving the loop honors
whatever the model decides rather than a hard-coded sequence).
"""
from __future__ import annotations

import pytest

from app.core.errors import LLMError
from app.services.github_service import GitHubService
from app.services.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolSpec
from app.services.llm.mock_provider import (
    MockLLMProvider,
    final_response,
    repeat_tool_call,
    tool_call_response,
)
from app.tools.github_tools import build_github_tools
from app.tools.registry import ToolRegistry

from tests.conftest import make_github_transport

REPO_ARGS = {"owner": "acme", "repo": "demo", "issue_number": 42}


class FailingLLMProvider(LLMProvider):
    """Simulates an LLM outage/configuration error."""

    name = "failing"

    def complete(self, messages, tools, *, response_format=None) -> LLMResponse:
        raise LLMError("LLM request failed: simulated outage")


def run_agent(script=None, state=None, max_steps=12, timeout=120, max_chars=4000, provider=None):
    github = GitHubService(token="gh_test_token", transport=make_github_transport(state or {}))
    registry = ToolRegistry(build_github_tools(github, max_output_chars=max_chars), max_output_chars=max_chars)
    provider = provider or MockLLMProvider(script=script)
    events = []
    approvals = []

    from app.agent.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(
        provider,
        registry,
        max_steps=max_steps,
        timeout_seconds=timeout,
        event_sink=lambda t, s, sm, tn: events.append((t, s, sm, tn)),
        approval_sink=lambda at, payload, rationale: (
            approvals.append({"action_type": at, "payload": payload, "rationale": rationale}),
            f"appr_{len(approvals)}",
        )[1],
    )
    outcome = orchestrator.run("acme/demo", 42)
    return outcome, events, approvals, state or {}, provider


class TestNormalFlow:
    def test_completes_with_valid_report(self, normal_script):
        outcome, events, _, _, _ = run_agent(normal_script)
        assert outcome.completed
        assert outcome.report is not None
        report = outcome.report
        assert report.issue_summary
        assert report.root_cause
        assert report.affected_files == ["src/auth/token_manager.py"]
        assert 0.0 <= report.confidence <= 1.0
        assert any(e.kind == "confirmed" for e in report.evidence)

    def test_tool_events_recorded_in_order(self, normal_script):
        _, events, _, _, _ = run_agent(normal_script)
        types = [t for t, _, _, _ in events]
        assert "tool_started" in types
        assert "tool_completed" in types
        started = [tn for t, _, _, tn in events if t == "tool_started"]
        assert started == ["get_issue", "search_repository", "get_file"]

    def test_tool_specs_and_context_passed_to_provider(self, normal_script):
        """The loop must hand the provider the real tool definitions and the
        growing conversation (task -> tool results) on every call."""
        outcome, _, _, _, provider = run_agent(normal_script)
        assert outcome.completed
        assert provider.call_count == 4  # 3 tool calls + final answer
        # Tool definitions were passed on every completion request.
        for requested in provider.requested_tools:
            names = [t.name for t in requested]
            assert "get_issue" in names
            assert "search_repository" in names
            assert "get_file" in names
            assert "add_issue_label" in names  # write tools are advertised too
        # Context is maintained: message list grows as tools return results.
        sizes = [len(msgs) for msgs in provider.requested_messages]
        assert sizes == sorted(sizes) and sizes[-1] > sizes[0]
        first, last = provider.requested_messages[0], provider.requested_messages[-1]
        assert [m.role for m in first[:2]] == ["system", "user"]
        tool_msgs = [m for m in last if m.role == "tool"]
        assert len(tool_msgs) == 3  # all three tool results are in context

    def test_context_driven_tool_selection(self):
        """The loop must honor whatever the model decides next based on the
        conversation — not a hard-coded sequence. Here the scripted provider
        inspects the actual get_issue result in the context and chooses to
        search related PRs only because the issue mentions one."""

        def decide(messages, tools):
            tool_msgs = [m.content for m in messages if m.role == "tool" and m.content]
            if not tool_msgs:
                return tool_call_response("get_issue", REPO_ARGS)
            if len(tool_msgs) == 1 and "token" in tool_msgs[0].lower():
                return tool_call_response(
                    "search_pull_requests",
                    {"owner": "acme", "repo": "demo", "query": "token refresh retry"},
                )
            return final_response({
                "issue_summary": "No related PR path taken.",
                "category": "bug",
                "priority": "low",
                "root_cause": "R.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.4,
                "warnings": [],
            })

        outcome, events, _, _, _ = run_agent([decide, decide, decide])
        assert outcome.completed
        started = [tn for t, _, _, tn in events if t == "tool_started"]
        # get_issue first, then the context-driven PR search — no other tools.
        assert started == ["get_issue", "search_pull_requests"]


class TestLLMFailure:
    def test_provider_failure_ends_run_cleanly(self):
        outcome, events, _, _, _ = run_agent(provider=FailingLLMProvider())
        assert not outcome.completed
        assert outcome.error_code == "llm_error"
        assert "simulated outage" in (outcome.error_message or "")

    def test_rate_limit_on_get_issue_is_fatal(self):
        script = [tool_call_response("get_issue", REPO_ARGS)]
        outcome, events, _, _, _ = run_agent(script, state={"rate_limit_issue": True})
        assert not outcome.completed
        assert "retrieve issue" in (outcome.error_message or "").lower()
        assert any("rate limit" in (sm or "").lower() for t, s, sm, _ in events if t == "tool_failed")


class TestMultiToolFlow:
    def test_full_investigation_with_related_issues_and_prs(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            tool_call_response("search_repository", {"owner": "acme", "repo": "demo", "query": "auth"}),
            tool_call_response("search_issues", {"owner": "acme", "repo": "demo", "query": "token"}),
            tool_call_response("search_pull_requests", {"owner": "acme", "repo": "demo", "query": "token"}),
            tool_call_response("get_file", {"owner": "acme", "repo": "demo", "path": "src/auth/token_manager.py"}),
            final_response({
                "issue_summary": "Token expiry mishandled; related history reviewed.",
                "category": "bug",
                "priority": "high",
                "root_cause": "refresh_token never rotates the stored token.",
                "evidence": [
                    {"source": "get_file:src/auth/token_manager.py", "quote": "def refresh_token", "kind": "confirmed"},
                    {"source": "search_issues", "quote": "issue #40 mentions missing retry", "kind": "confirmed"},
                    {"source": "inference", "quote": "likely race in rotation", "kind": "hypothesis"},
                ],
                "affected_files": ["src/auth/token_manager.py"],
                "resolution_steps": ["Rotate and persist the token."],
                "test_plan": ["Unit test expiry rotation."],
                "confidence": 0.9,
                "warnings": [],
            }),
        ]
        outcome, events, _, _, _ = run_agent(script)
        assert outcome.completed
        started = [tn for t, _, _, tn in events if t == "tool_started"]
        assert started == [
            "get_issue",
            "search_repository",
            "search_issues",
            "search_pull_requests",
            "get_file",
        ]
        kinds = {e.kind for e in outcome.report.evidence}
        assert kinds == {"confirmed", "hypothesis"}


class TestFailureScenarios:
    def test_issue_not_found_terminates(self):
        script = [tool_call_response("get_issue", {"owner": "acme", "repo": "demo", "issue_number": 999})]
        outcome, events, _, _, _ = run_agent(script)
        assert not outcome.completed
        assert "retrieve issue" in (outcome.error_message or "").lower()
        failed = [sm for t, s, sm, _ in events if t == "tool_failed"]
        assert any("not found" in (sm or "").lower() for sm in failed)

    def test_empty_search_still_completes(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            tool_call_response("search_repository", {"owner": "acme", "repo": "demo", "query": "noresults"}),
            final_response({
                "issue_summary": "No matching code found.",
                "category": "question",
                "priority": "low",
                "root_cause": "Unknown; no repository matches.",
                "evidence": [
                    {"source": "search_repository:noresults", "quote": "no matches", "kind": "confirmed"}
                ],
                "affected_files": [],
                "resolution_steps": ["Ask the reporter for more detail."],
                "test_plan": [],
                "confidence": 0.3,
                "warnings": ["No code evidence found."],
            }),
        ]
        outcome, events, _, _, _ = run_agent(script)
        assert outcome.completed
        assert any(t == "tool_completed" for t, _, _, _ in events)

    def test_rate_limited_search_falls_back_and_completes(self):
        """A rate-limited code search falls back to a tree path match and the
        agent completes with the fallback evidence."""
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            tool_call_response("search_repository", {"owner": "acme", "repo": "demo", "query": "ratelimit auth"}),
            final_response({
                "issue_summary": "Rate limited but recovered via fallback search.",
                "category": "bug",
                "priority": "medium",
                "root_cause": "Could not code-search; used tree path match.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.2,
                "warnings": ["Repository search used the fallback path match."],
            }),
        ]
        outcome, events, _, _, _ = run_agent(script)
        assert outcome.completed
        # The search tool completed via the fallback (path matches returned).
        completed = [(tn, sm) for t, s, sm, tn in events if t == "tool_completed"]
        assert any(tn == "search_repository" for tn, _ in completed)

    def test_tool_failure_then_recovery(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            tool_call_response("get_file", {"owner": "acme", "repo": "demo", "path": "src/auth/missing.py"}),
            tool_call_response("get_file", {"owner": "acme", "repo": "demo", "path": "src/auth/token_manager.py"}),
            final_response({
                "issue_summary": "Recovered after a failed file read.",
                "category": "bug",
                "priority": "medium",
                "root_cause": "Token not refreshed.",
                "evidence": [
                    {"source": "get_file:src/auth/token_manager.py", "quote": "refresh_token", "kind": "confirmed"}
                ],
                "affected_files": ["src/auth/token_manager.py"],
                "resolution_steps": ["Fix refresh."],
                "test_plan": ["Test refresh."],
                "confidence": 0.7,
                "warnings": [],
            }),
        ]
        outcome, events, _, _, _ = run_agent(script)
        assert outcome.completed
        failed = [tn for t, s, sm, tn in events if t == "tool_failed"]
        assert "get_file" in failed


class TestStructuredOutput:
    def test_invalid_then_valid_retry(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            final_response("this is not json at all"),
            final_response({
                "issue_summary": "Retried successfully.",
                "category": "bug",
                "priority": "low",
                "root_cause": "Root cause.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.5,
                "warnings": [],
            }),
        ]
        outcome, events, _, _, _ = run_agent(script)
        assert outcome.completed
        assert outcome.report is not None
        assert outcome.report.issue_summary == "Retried successfully."
        retries = [s for t, s, sm, _ in events if t == "status" and s == "retry"]
        assert len(retries) == 1

    def test_invalid_json_all_retries_exhausted(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            final_response("not json"),
            final_response("still not json"),
            final_response("definitely not json"),
        ]
        outcome, events, _, _, _ = run_agent(script)
        assert not outcome.completed
        assert outcome.error_code == "structured_output_invalid"

    def test_wrong_schema_triggers_retry(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            final_response({"unexpected_key": True}),
            final_response({
                "issue_summary": "Fixed schema.",
                "category": "bug",
                "priority": "low",
                "root_cause": "R.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.6,
                "warnings": [],
            }),
        ]
        outcome, _, _, _, _ = run_agent(script)
        assert outcome.completed
        assert outcome.report.issue_summary == "Fixed schema."


class TestLimits:
    def test_step_limit_reached(self):
        script = repeat_tool_call("get_issue", REPO_ARGS, times=50)
        outcome, events, _, _, _ = run_agent(script, max_steps=3)
        assert not outcome.completed
        assert outcome.limit_kind == "steps"
        assert "maximum" in (outcome.error_message or "").lower()
        # The agent stopped calling tools once the budget was exhausted.
        assert len([t for t, _, _, _ in events if t == "tool_completed"]) <= 3


class TestWriteApproval:
    def test_write_tool_call_creates_approval_and_never_writes(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            tool_call_response("add_issue_label", {"owner": "acme", "repo": "demo", "issue_number": 42, "labels": ["bug"]}),
            final_response({
                "issue_summary": "Issue investigated.",
                "category": "bug",
                "priority": "high",
                "root_cause": "Token not refreshed.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.8,
                "warnings": [],
            }),
        ]
        outcome, events, approvals, state, _ = run_agent(script)
        assert outcome.completed
        assert len(approvals) == 1
        assert approvals[0]["action_type"] == "add_issue_label"
        assert state.get("label_posts") in (None, [])  # never executed

    def test_report_proposed_actions_surface_in_outcome(self):
        script = [
            tool_call_response("get_issue", REPO_ARGS),
            final_response({
                "issue_summary": "Issue investigated.",
                "category": "bug",
                "priority": "high",
                "root_cause": "Token not refreshed.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.8,
                "warnings": [],
                "proposed_actions": [
                    {
                        "action_type": "add_issue_label",
                        "payload": {"owner": "acme", "repo": "demo", "issue_number": 42, "labels": ["triage"]},
                        "rationale": "Classify the issue.",
                    }
                ],
            }),
        ]
        outcome, _, _, _, _ = run_agent(script)
        assert outcome.completed
        assert outcome.report.proposed_actions[0].action_type == "add_issue_label"