"""Shared pytest fixtures.

External dependencies (GitHub API, LLM) are mocked so tests are
deterministic and offline: GitHub calls go through httpx.MockTransport and
LLM calls use the scriptable MockLLMProvider.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault(
    "GITPILOT_DATABASE_PATH",
    os.path.join(tempfile.gettempdir(), "gitpilot_default_test.db"),
)

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.analysis_service import AnalysisService
from app.services.github_service import GitHubService
from app.services.llm.mock_provider import (
    MockLLMProvider,
    final_response,
    tool_call_response,
)

# ---------------------------------------------------------------------------
# Fake repository data
# ---------------------------------------------------------------------------

ISSUE_42 = {
    "number": 42,
    "title": "Auth token refresh fails after expiry",
    "body": "The session token is not refreshed after it expires, causing 401s.",
    "state": "open",
    "user": {"login": "alice"},
    "labels": [{"name": "bug"}, {"name": "auth"}],
    "created_at": "2026-01-05T10:00:00Z",
    "updated_at": "2026-01-06T10:00:00Z",
    "closed_at": None,
    "html_url": "https://github.com/acme/demo/issues/42",
}

COMMENTS_42 = [
    {
        "user": {"login": "bob"},
        "body": "I can reproduce this with a short-lived token.",
    }
]

SEARCH_CODE_RESULTS = {
    "items": [
        {
            "path": "src/auth/token_manager.py",
            "name": "token_manager.py",
            "html_url": "https://github.com/acme/demo/blob/main/src/auth/token_manager.py",
            "text_matches": [{"fragment": "def refresh_token(self): ..."}],
        },
        {
            "path": "src/auth/session.py",
            "name": "session.py",
            "html_url": "https://github.com/acme/demo/blob/main/src/auth/session.py",
            "text_matches": [{"fragment": "token = self._refresh()"}],
        },
    ]
}

SEARCH_ISSUES_RESULTS = {
    "items": [
        {
            "number": 40,
            "title": "Token expiry handling missing retry",
            "state": "open",
            "labels": [{"name": "auth"}],
            "created_at": "2026-01-02T10:00:00Z",
            "html_url": "https://github.com/acme/demo/issues/40",
        }
    ]
}

SEARCH_PRS_RESULTS = {
    "items": [
        {
            "number": 39,
            "title": "Add token refresh retry logic",
            "state": "merged",
            "created_at": "2025-12-20T10:00:00Z",
            "html_url": "https://github.com/acme/demo/pull/39",
        }
    ]
}

TOKEN_MANAGER_CONTENT = (
    "class TokenManager:\n"
    "    def refresh_token(self):\n"
    "        # BUG: never updates self._token after expiry\n"
    "        return self._token\n"
)


REPO_META = {"default_branch": "main", "full_name": "acme/demo"}

TREE_MAIN = {
    "sha": "abc123",
    "truncated": False,
    "tree": [
        {"type": "blob", "path": "README.md", "sha": "s1"},
        {"type": "blob", "path": "src/auth/token_manager.py", "sha": "s2"},
        {"type": "blob", "path": "src/auth/session.py", "sha": "s3"},
        {"type": "blob", "path": "src/app.py", "sha": "s4"},
        {"type": "tree", "path": "src/auth", "sha": "s5"},
    ],
}


def make_github_transport(state: dict):
    """Build an httpx.MockTransport serving canned GitHub responses.

    ``state`` records write attempts (labels/comments) so tests can assert
    that approved actions were executed and unapproved ones were not.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        # ---- repository metadata / tree (search fallback) ----
        if path == "/repos/acme/demo" and not state.get("tree_unavailable"):
            return httpx.Response(200, json=REPO_META)
        if path == "/repos/acme/demo/git/trees/main" and not state.get("tree_unavailable"):
            return httpx.Response(200, json=TREE_MAIN)

        # ---- issue retrieval ----
        if path == "/repos/acme/demo/issues/42":
            if state.get("rate_limit_issue"):
                return httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers={"x-ratelimit-remaining": "0"},
                )
            return httpx.Response(200, json=ISSUE_42)
        if path == "/repos/acme/demo/issues/999":
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/repos/acme/demo/issues/42/comments" and method == "GET":
            return httpx.Response(200, json=COMMENTS_42)

        # ---- code search ----
        if path == "/search/code":
            query = request.url.params.get("q", "")
            if "ratelimit" in query or state.get("rate_limit_search"):
                return httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers={"x-ratelimit-remaining": "0"},
                )
            if state.get("search_auth_error"):
                return httpx.Response(403, json={"message": "Forbidden"})
            if state.get("search_failure"):
                return httpx.Response(500, json={"message": "server error"})
            if "noresults" in query:
                return httpx.Response(200, json={"items": []})
            return httpx.Response(200, json=SEARCH_CODE_RESULTS)

        # ---- issue/PR search ----
        if path == "/search/issues":
            query = request.url.params.get("q", "")
            if "type:pr" in query:
                return httpx.Response(200, json=SEARCH_PRS_RESULTS)
            return httpx.Response(200, json=SEARCH_ISSUES_RESULTS)

        # ---- file retrieval ----
        if path == "/repos/acme/demo/contents/src/app.py":
            app_py = (
                "from auth import validate_login\n\n"
                "def handle_login(payload):\n"
                "    return login_user(payload['email'], payload['password'])\n"
            )
            return httpx.Response(
                200,
                json={
                    "path": "src/app.py",
                    "type": "file",
                    "size": len(app_py),
                    "encoding": "base64",
                    "content": base64.b64encode(app_py.encode()).decode(),
                },
            )
        if path == "/repos/acme/demo/contents/src/auth/token_manager.py":
            return httpx.Response(
                200,
                json={
                    "path": "src/auth/token_manager.py",
                    "type": "file",
                    "size": len(TOKEN_MANAGER_CONTENT),
                    "encoding": "base64",
                    "content": base64.b64encode(TOKEN_MANAGER_CONTENT.encode()).decode(),
                },
            )
        if path == "/repos/acme/demo/contents/src/auth/missing.py":
            return httpx.Response(404, json={"message": "Not Found"})

        # ---- write actions (recorded, never auto-executed) ----
        if path == "/repos/acme/demo/issues/42/labels" and method == "POST":
            state.setdefault("label_posts", []).append(request.content.decode())
            return httpx.Response(200, json=[{"name": "bug"}])
        if path == "/repos/acme/demo/issues/42/comments" and method == "POST":
            state.setdefault("comment_posts", []).append(request.content.decode())
            return httpx.Response(
                201, json={"id": 77, "html_url": "https://github.com/acme/demo/issues/42#issuecomment-77"}
            )

        # ---- anything else ----
        return httpx.Response(404, json={"message": f"unexpected: {method} {path}"})

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def github_state() -> dict:
    return {}


@pytest.fixture
def github_transport(github_state):
    return make_github_transport(github_state)


def make_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        github_token="gh_test_token",
        github_api_base_url="https://api.github.com",
        llm_provider="mock",
        openai_api_key="",
        database_path=str(tmp_path / "gitpilot_test.db"),
        frontend_origin="http://localhost:3000",
        agent_max_steps=12,
        agent_timeout_seconds=120,
        tool_max_output_chars=4000,
        structured_output_retries=2,
    )
    defaults.update(overrides)
    s = Settings()
    for key, value in defaults.items():
        setattr(s, key, value)
    return s


@pytest.fixture
def normal_script():
    """Deterministic investigation flow: issue -> search -> file -> report."""
    report = {
        "issue_summary": "Auth token refresh fails after expiry, causing 401s.",
        "category": "bug",
        "priority": "high",
        "root_cause": (
            "TokenManager.refresh_token never updates the stored token after "
            "expiry (confirmed in src/auth/token_manager.py)."
        ),
        "evidence": [
            {
                "source": "get_file:src/auth/token_manager.py",
                "quote": "def refresh_token(self): return self._token",
                "kind": "confirmed",
            },
            {
                "source": "search_repository:auth",
                "quote": "src/auth/token_manager.py matched 'auth'",
                "kind": "confirmed",
            },
        ],
        "affected_files": ["src/auth/token_manager.py"],
        "resolution_steps": [
            "Update refresh_token to rotate the token and persist it."
        ],
        "test_plan": ["Unit test token rotation after expiry."],
        "confidence": 0.85,
        "warnings": ["Search results are mock data."],
    }
    return [
        tool_call_response("get_issue", {"owner": "acme", "repo": "demo", "issue_number": 42}),
        tool_call_response(
            "search_repository", {"owner": "acme", "repo": "demo", "query": "auth"}
        ),
        tool_call_response(
            "get_file", {"owner": "acme", "repo": "demo", "path": "src/auth/token_manager.py"}
        ),
        final_response(report),
    ]


@pytest.fixture
def make_service():
    """Factory producing a fully-wired AnalysisService with mocks."""

    def _make(tmp_path, script=None, state=None, **overrides):
        from app.db.database import create_engine_for, init_db, make_session_factory

        settings = make_settings(tmp_path, **overrides)
        engine = create_engine_for(settings.database_path)
        init_db(engine)
        session_factory = make_session_factory(engine)
        transport = make_github_transport(state or {})
        github = GitHubService(token="gh_test_token", transport=transport)
        provider = MockLLMProvider(script=script)
        return AnalysisService(session_factory, github, provider, settings)

    return _make


@pytest.fixture
def make_client():
    """Factory producing a TestClient with injected mocks."""

    def _make(tmp_path, script=None, state=None, provider=None, **overrides):
        settings = make_settings(tmp_path, **overrides)
        transport = make_github_transport(state or {})
        llm = provider or MockLLMProvider(script=script)
        app = create_app(
            settings=settings,
            github_transport=transport,
            llm_provider=llm,
        )
        return TestClient(app)

    return _make