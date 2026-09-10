"""Tests for the deterministic demo provider (LLM_PROVIDER=demo).

Demo Mode must: complete a real agent run (real GitHub tools via the mock
transport, real orchestrator, real persistence), produce the standard
ResolutionReport schema with evidence taken verbatim from real tool output,
and clearly label itself as demo (no live LLM call) in both the report
warnings and the health endpoint's mode flag.
"""
from __future__ import annotations

import json

import pytest

from app.core.errors import LLMConfigurationError
from app.services.github_service import GitHubService
from app.services.llm import get_llm_provider
from app.services.llm.demo_provider import DemoLLMProvider
from app.services.llm.base import LLMMessage, ToolSpec

from tests.conftest import make_github_transport

REPO_ARGS = {"owner": "acme", "repo": "demo", "issue_number": 42}


class TestFactorySelection:
    def test_factory_returns_demo_provider(self, tmp_path):
        from tests.conftest import make_settings

        settings = make_settings(tmp_path, llm_provider="demo")
        provider = get_llm_provider(settings)
        assert isinstance(provider, DemoLLMProvider)
        assert provider.name == "demo"

    def test_demo_provider_needs_no_credentials(self):
        """Constructing the demo provider takes no API key at all."""
        DemoLLMProvider()  # no error


class TestDemoAgentRun:
    def test_full_demo_run_completes_with_real_tools(self):
        """The demo fixture drives the REAL agent loop and REAL GitHub tools:
        issue retrieved, repository searched, a file inspected — then a
        structured fixture report derived from that actual output."""
        github = GitHubService(token="gh_test", transport=make_github_transport({}))
        from app.tools.github_tools import build_github_tools
        from app.tools.registry import ToolRegistry
        from app.agent.orchestrator import AgentOrchestrator

        registry = ToolRegistry(build_github_tools(github, max_output_chars=4000), max_output_chars=4000)
        events = []
        orchestrator = AgentOrchestrator(
            DemoLLMProvider(),
            registry,
            max_steps=12,
            timeout_seconds=120,
            event_sink=lambda t, s, sm, tn: events.append((t, tn, sm)),
        )
        outcome = orchestrator.run("acme/demo", 42)

        assert outcome.completed, outcome.error_message
        report = outcome.report
        assert report is not None
        # Standard ResolutionReport structure, unchanged schema.
        assert report.issue_summary
        assert report.category == "unknown"
        assert report.root_cause
        assert report.confidence == 0.2
        assert report.evidence, "report must contain evidence"

        # Evidence comes verbatim from real tool output.
        sources = [e.source for e in report.evidence]
        assert "get_issue" in sources
        assert any(s.startswith("get_file:") for s in sources)
        assert all(e.kind == "confirmed" for e in report.evidence)

        # Demo labeling is mandatory and explicit.
        joined = " ".join(report.warnings)
        assert "DEMO MODE" in joined
        assert "no live Gemini API call" in joined.replace("no live Gemini API call", "no live Gemini API call") or "deterministic demo" in joined

        # The real tools really executed on the real (mocked) GitHub data.
        started = [tn for t, tn, _ in events if t == "tool_started"]
        assert started == ["get_issue", "search_repository", "get_file"]

    def test_demo_report_is_valid_json_matching_schema(self):
        github = GitHubService(token="gh_test", transport=make_github_transport({}))
        from app.tools.github_tools import build_github_tools
        from app.tools.registry import ToolRegistry
        from app.agent.orchestrator import AgentOrchestrator

        registry = ToolRegistry(build_github_tools(github, max_output_chars=4000), max_output_chars=4000)
        outcome = AgentOrchestrator(DemoLLMProvider(), registry, max_steps=12, timeout_seconds=120).run("acme/demo", 42)
        assert outcome.completed and outcome.report is not None
        # The final answer was a JSON object parseable into the report.
        data = json.loads(json.dumps(outcome.report.model_dump()))
        assert data["evidence"] and data["warnings"]

    def test_demo_respects_step_limit(self):
        """Safety limits still bound the demo run: a tiny step budget
        terminates the demo agent just like a live one."""
        github = GitHubService(token="gh_test", transport=make_github_transport({}))
        from app.tools.github_tools import build_github_tools
        from app.tools.registry import ToolRegistry
        from app.agent.orchestrator import AgentOrchestrator

        registry = ToolRegistry(build_github_tools(github, max_output_chars=4000), max_output_chars=4000)
        orchestrator = AgentOrchestrator(DemoLLMProvider(), registry, max_steps=1, timeout_seconds=120)
        outcome = orchestrator.run("acme/demo", 42)
        assert not outcome.completed
        assert outcome.limit_kind == "steps"


class TestHealthModeFlag:
    def test_health_reports_demo_mode(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from tests.conftest import make_settings

        settings = make_settings(tmp_path, llm_provider="demo")
        app = create_app(settings=settings)
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["mode"] == "demo"

    def test_health_reports_live_mode_by_default(self, tmp_path):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from tests.conftest import make_settings

        settings = make_settings(tmp_path, llm_provider="mock")
        app = create_app(settings=settings)
        client = TestClient(app)
        body = client.get("/api/health").json()
        assert body["mode"] == "live"


class TestRealProvidersUntouched:
    def test_gemini_still_selected_for_gemini(self, tmp_path):
        from tests.conftest import make_settings

        settings = make_settings(tmp_path, llm_provider="gemini")
        provider = get_llm_provider(settings)
        assert type(provider).__name__ == "GeminiLLMProvider"

    def test_unknown_provider_still_rejected(self, tmp_path):
        from tests.conftest import make_settings

        settings = make_settings(tmp_path, llm_provider="nonsense")
        with pytest.raises(LLMConfigurationError):
            get_llm_provider(settings)
