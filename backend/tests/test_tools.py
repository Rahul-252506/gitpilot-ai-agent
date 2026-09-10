"""Tool-layer tests: argument validation, output bounding, write safety."""
from __future__ import annotations

from app.services.github_service import GitHubService
from app.tools.github_tools import build_github_tools
from app.tools.registry import ToolRegistry
from app.tools.truncation import truncate

from tests.conftest import make_github_transport


def build_registry(state=None, max_chars: int = 2000) -> ToolRegistry:
    github = GitHubService(token="gh_test_token", transport=make_github_transport(state or {}))
    return ToolRegistry(build_github_tools(github, max_output_chars=max_chars), max_output_chars=max_chars)


class TestArgumentValidation:
    def test_get_issue_invalid_number(self):
        result = build_registry().execute("get_issue", {"owner": "acme", "repo": "demo", "issue_number": -5})
        assert result.ok is False
        assert "issue_number" in (result.error or "")

    def test_get_issue_missing_owner(self):
        result = build_registry().execute("get_issue", {"repo": "demo", "issue_number": 42})
        assert result.ok is False
        assert "owner" in (result.error or "")

    def test_search_empty_query(self):
        result = build_registry().execute("search_repository", {"owner": "acme", "repo": "demo", "query": ""})
        assert result.ok is False

    def test_get_file_missing_path(self):
        result = build_registry().execute("get_file", {"owner": "acme", "repo": "demo"})
        assert result.ok is False

    def test_unknown_tool(self):
        result = build_registry().execute("frobnicate", {})
        assert result.ok is False
        assert "Unknown tool" in (result.error or "")


class TestBounding:
    def test_large_file_content_is_truncated(self):
        registry = build_registry(max_chars=100)
        result = registry.execute("get_file", {"owner": "acme", "repo": "demo", "path": "src/auth/token_manager.py"})
        assert result.ok
        assert len(result.text) <= 100
        assert "truncated" in result.text

    def test_registry_rebounds_even_large_results(self):
        registry = build_registry(max_chars=100)
        result = registry.execute("get_issue", {"owner": "acme", "repo": "demo", "issue_number": 42})
        assert result.ok
        assert len(result.text) <= 100


class TestWriteSafety:
    def test_write_tool_never_posts(self):
        state = {}
        registry = build_registry(state)
        result = registry.execute("add_issue_label", {"owner": "acme", "repo": "demo", "issue_number": 42, "labels": ["bug"]})
        assert result.pending_approval is True
        assert state.get("label_posts") in (None, [])  # nothing written

    def test_comment_write_never_posts(self):
        state = {}
        registry = build_registry(state)
        result = registry.execute("add_issue_comment", {"owner": "acme", "repo": "demo", "issue_number": 42, "body": "hi"})
        assert result.pending_approval is True
        assert state.get("comment_posts") in (None, [])

    def test_write_tool_argument_validation(self):
        result = build_registry().execute("add_issue_label", {"owner": "acme", "repo": "demo", "issue_number": 42, "labels": []})
        assert result.ok is False


class TestTruncationUtil:
    def test_short_text_untouched(self):
        assert truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        out = truncate("x" * 500, 100)
        assert len(out) <= 100
        assert "truncated" in out

    def test_max_chars_zero(self):
        assert "truncated" in truncate("anything", 0)

    def test_truncate_lines(self):
        from app.tools.truncation import truncate_lines

        out = truncate_lines("a\nb\nc\nd", max_lines=2, max_chars=1000)
        assert "truncated" in out
        assert out.count("\n") >= 2