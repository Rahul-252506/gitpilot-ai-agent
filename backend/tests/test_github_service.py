"""GitHub service tests using httpx.MockTransport (no network)."""
from __future__ import annotations

import pytest

from app.core.errors import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from app.services.github_service import GitHubService

from tests.conftest import make_github_transport


def make_service(state=None):
    state = {} if state is None else state
    return GitHubService(token="gh_test_token", transport=make_github_transport(state))


class TestGetIssue:
    def test_success(self):
        issue = make_service().get_issue("acme", "demo", 42)
        assert issue["title"] == "Auth token refresh fails after expiry"
        assert issue["state"] == "open"
        assert issue["author"] == "alice"
        assert "bug" in issue["labels"]
        assert issue["comments_count"] == 1
        assert issue["comments"][0]["author"] == "bob"

    def test_not_found(self):
        with pytest.raises(GitHubNotFoundError):
            make_service().get_issue("acme", "demo", 999)

    def test_missing_token(self):
        service = GitHubService(token="", transport=make_github_transport({}))
        with pytest.raises(GitHubAuthError):
            service.get_issue("acme", "demo", 42)


class TestSearch:
    def test_code_search_with_snippets(self):
        results = make_service().search_repository("acme", "demo", "auth")
        assert len(results) == 2
        assert results[0]["path"] == "src/auth/token_manager.py"
        assert "refresh_token" in results[0]["snippet"]

    def test_code_search_falls_back_to_tree_on_rate_limit(self):
        service = make_service({"rate_limit_search": True})
        results = service.search_repository("acme", "demo", "auth token refresh")
        paths = [r["path"] for r in results]
        assert "src/auth/token_manager.py" in paths
        assert "src/auth/session.py" in paths
        # content scan legitimately adds files whose content mentions a term
        assert all(r["snippet"] for r in results)

    def test_code_search_falls_back_to_tree_on_auth_error(self):
        service = make_service({"search_auth_error": True})
        results = service.search_repository("acme", "demo", "session")
        assert [r["path"] for r in results] == ["src/auth/session.py"]

    def test_fallback_no_terms_returns_empty(self):
        service = make_service({"rate_limit_search": True})
        assert service.search_repository("acme", "demo", "a b") == []

    def test_empty_index_results_fall_back_to_tree(self):
        """GitHub's code-search index often misses tiny/new repos; an empty
        result must trigger the tree search so the tool stays useful."""
        service = make_service({})  # code search returns [] for 'noresults'
        results = service.search_repository("acme", "demo", "noresults auth")
        paths = [r["path"] for r in results]
        assert "src/auth/token_manager.py" in paths
        assert all(r["snippet"] for r in results)

    def test_small_repo_content_scan_finds_symbols(self):
        """Symbol searches (e.g. 'login_user') must match real file content
        in small repositories — with a genuine matched line as snippet."""
        service = make_service({"rate_limit_search": True})
        results = service.search_repository("acme", "demo", "login_user")
        by_path = {r["path"]: r for r in results}
        assert "src/app.py" in by_path
        assert "login_user" in by_path["src/app.py"]["snippet"]

    def test_code_search_rate_limit(self):
        service = make_service({"rate_limit_search": True, "tree_unavailable": True})
        with pytest.raises(GitHubRateLimitError):
            service.search_repository("acme", "demo", "auth")

    def test_issue_search(self):
        results = make_service().search_issues("acme", "demo", "token")
        assert results[0]["number"] == 40

    def test_pr_search(self):
        results = make_service().search_pull_requests("acme", "demo", "token")
        assert results[0]["number"] == 39
        assert results[0]["state"] == "merged"


class TestGetFile:
    def test_decodes_base64(self):
        data = make_service().get_file("acme", "demo", "src/auth/token_manager.py")
        assert "refresh_token" in data["content"]
        assert data["type"] == "file"

    def test_not_found(self):
        with pytest.raises(GitHubNotFoundError):
            make_service().get_file("acme", "demo", "src/auth/missing.py")

    def test_with_ref(self):
        data = make_service().get_file("acme", "demo", "src/auth/token_manager.py", ref="main")
        assert data["path"] == "src/auth/token_manager.py"


class TestWrites:
    def test_add_issue_label_posts_correct_payload(self):
        state = {}
        service = make_service(state)
        result = service.add_issue_label("acme", "demo", 42, ["bug", "priority-high"])
        assert result["applied"] == ["bug"]
        import json

        posted = json.loads(state["label_posts"][0])
        assert posted == {"labels": ["bug", "priority-high"]}

    def test_add_issue_comment_posts_correct_payload(self):
        state = {}
        service = make_service(state)
        result = service.add_issue_comment("acme", "demo", 42, "Fixed in #43")
        assert result["comment_id"] == 77
        import json

        posted = json.loads(state["comment_posts"][0])
        assert posted == {"body": "Fixed in #43"}