"""GitHub REST API integration.

All GitHub access flows through this service — the agent never talks to
GitHub directly and never sees the token. The token stays server-side in
the Authorization header of the HTTP client.
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

import httpx

from app.core.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubTimeoutError,
)

logger = logging.getLogger("gitpilot")

SEARCH_TEXT_MATCH_ACCEPT = "application/vnd.github.text-match+json"

# Small-repo content scan: when the code-search index does not cover a repo
# (typical for tiny/new repositories), we can safely scan the files directly.
# Strictly bounded so this never turns into unrestricted crawling.
_SMALL_REPO_BLOB_LIMIT = 25
_CONTENT_SCAN_FILE_LIMIT = 12
_MAX_SCAN_FILE_BYTES = 100_000


def _first_matching_line(content: str, terms: list[str]) -> str:
    """Return the first line containing any query term, or empty string."""
    for line in content.splitlines():
        lowered = line.lower()
        if any(term in lowered for term in terms):
            return line.strip()[:200]
    return ""


class GitHubService:
    """Thin, safe wrapper around the GitHub REST API."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    # ---------------- client ----------------
    def _client(self) -> httpx.Client:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "headers": headers,
            "timeout": httpx.Timeout(self._timeout),
            "follow_redirects": True,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    # ---------------- request plumbing ----------------
    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self._token:
            raise GitHubAuthError(
                "GitHub authentication is not configured. "
                "Set the GITHUB_TOKEN environment variable and restart the backend."
            )
        try:
            with self._client() as client:
                response = client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise GitHubTimeoutError(
                f"GitHub request timed out after {self._timeout}s: {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise GitHubNetworkError(f"GitHub request failed: {exc}") from exc

        if response.status_code == 404:
            raise GitHubNotFoundError(f"GitHub resource not found: {path}")
        if response.status_code in (401, 403):
            if response.headers.get("x-ratelimit-remaining") == "0":
                raise GitHubRateLimitError(
                    "GitHub rate limit reached. Try again later or use a token "
                    "with a higher quota."
                )
            raise GitHubAuthError(
                f"GitHub authentication failed (HTTP {response.status_code}) for "
                f"{path}. Check the GITHUB_TOKEN value and its scopes."
            )
        if response.status_code == 429:
            raise GitHubRateLimitError(
                "GitHub rate limit reached (HTTP 429). Try again later."
            )
        if response.status_code >= 500:
            raise GitHubNetworkError(
                f"GitHub server error (HTTP {response.status_code}) for {path}."
            )
        if response.status_code >= 400:
            raise GitHubNetworkError(
                f"GitHub request failed (HTTP {response.status_code}) for {path}: "
                f"{response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubNetworkError(
                f"GitHub returned a non-JSON response for {path}."
            ) from exc

    def _request_items(self, method: str, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        payload = self._request(method, path, **kwargs)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return payload["items"]
        return []

    # ---------------- read tools ----------------
    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        data = self._request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")
        comments_data = self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            params={"per_page": 5},
        )
        comments = [
            {
                "author": c.get("user", {}).get("login") if c.get("user") else "unknown",
                "body": c.get("body", ""),
            }
            for c in comments_data
        ]
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "body": data.get("body") or "",
            "state": data.get("state"),
            "author": data.get("user", {}).get("login") if data.get("user") else "unknown",
            "labels": [label.get("name") for label in data.get("labels", [])],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "closed_at": data.get("closed_at"),
            "html_url": data.get("html_url"),
            "is_pull_request": "pull_request" in data,
            "comments": comments,
            "comments_count": len(comments),
        }

    def search_repository(
        self, owner: str, repo: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search code inside a repository.

        Primary path: GitHub code search (file paths + matching snippets).
        Two known limitations are handled safely:
        1. The code-search endpoint has stricter auth/rate-limit policies —
           fall back to a repository-tree path match (paths only, no
           snippets) rather than pretending unrestricted search exists.
        2. GitHub's code-search index often does not cover very small/new
           repositories, returning zero results — fall back to the tree
           match in that case too.
        """
        try:
            results = self._code_search(owner, repo, query, limit)
        except (GitHubRateLimitError, GitHubAuthError) as primary_error:
            try:
                return self._tree_path_search(owner, repo, query, limit)
            except GitHubError:
                # Both paths failed — surface the original, more specific error.
                raise primary_error from None
        if not results:
            # Code search worked but the index does not cover this repo.
            try:
                return self._tree_path_search(owner, repo, query, limit)
            except GitHubError:
                return []
        return results

    def _code_search(
        self, owner: str, repo: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        q = f"repo:{owner}/{repo} {query}"
        items = self._request_items(
            "GET",
            "/search/code",
            params={"q": q, "per_page": min(limit, 10)},
            headers={"Accept": SEARCH_TEXT_MATCH_ACCEPT},
        )
        results: list[dict[str, Any]] = []
        for item in items:
            snippet = ""
            matches = item.get("text_matches") or []
            if matches:
                snippet = " | ".join(
                    m.get("fragment", "")[:300] for m in matches[:2]
                )
            results.append(
                {
                    "path": item.get("path"),
                    "name": item.get("name"),
                    "html_url": item.get("html_url"),
                    "snippet": snippet,
                }
            )
        return results

    def _tree_path_search(
        self, owner: str, repo: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fallback search via the repository tree.

        1. Path matching — always available through the plain REST API.
        2. Content scan — only for small repositories (bounded file count and
           file size), fetching each candidate file through the normal
           contents endpoint and matching the query terms against real file
           lines. This keeps symbol searches (e.g. ``login_user``) working on
           tiny repositories that GitHub's code-search index does not cover.
        """
        repo_data = self._request("GET", f"/repos/{owner}/{repo}")
        branch = repo_data.get("default_branch") or "main"
        tree = self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{branch}",
            params={"recursive": "true"},
        )
        blobs = [
            entry
            for entry in tree.get("tree", [])
            if entry.get("type") == "blob" and entry.get("path")
        ]
        terms = [
            t.lower()
            for t in re.split(r"[^A-Za-z0-9_.-]+", query)
            if len(t) >= 3
        ][:5]
        if not terms:
            return []

        matches: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(path: str, snippet: str) -> bool:
            if path in seen or len(matches) >= limit:
                return False
            seen.add(path)
            matches.append(
                {
                    "path": path,
                    "name": path.rsplit("/", 1)[-1],
                    "html_url": f"https://github.com/{owner}/{repo}/blob/{branch}/{path}",
                    "snippet": snippet,
                }
            )
            return len(matches) >= limit

        # 1. Path matches (cheap; no extra requests).
        for blob in blobs:
            path = blob["path"]
            lowered = path.lower()
            if any(term in lowered for term in terms):
                if add(
                    path,
                    "(path match — snippets unavailable via fallback search)",
                ):
                    return matches

        # 2. Content scan, strictly bounded to small repositories/files.
        if len(blobs) <= _SMALL_REPO_BLOB_LIMIT:
            scanned = 0
            for blob in blobs:
                if scanned >= _CONTENT_SCAN_FILE_LIMIT or len(matches) >= limit:
                    break
                path = blob["path"]
                if path in seen:
                    continue
                if (blob.get("size") or 0) > _MAX_SCAN_FILE_BYTES:
                    continue
                scanned += 1
                try:
                    data = self.get_file(owner, repo, path, ref=branch)
                except GitHubError:
                    continue  # skip unreadable files, keep scanning
                snippet = _first_matching_line(data.get("content") or "", terms)
                if snippet:
                    add(path, snippet)
        return matches

    def get_file(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> dict[str, Any]:
        params = {}
        if ref:
            params["ref"] = ref
        data = self._request(
            "GET", f"/repos/{owner}/{repo}/contents/{path}", params=params
        )
        if isinstance(data, list):
            # Directory listing requested — return names only.
            entries = [
                {"name": entry.get("name"), "type": entry.get("type")}
                for entry in data
            ]
            return {"path": path, "type": "directory", "entries": entries}
        content = ""
        encoding = data.get("encoding")
        if encoding == "base64" and data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return {
            "path": data.get("path"),
            "type": data.get("type"),
            "size": data.get("size"),
            "content": content,
        }

    def search_issues(
        self, owner: str, repo: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        items = self._request_items(
            "GET",
            "/search/issues",
            params={
                "q": f"repo:{owner}/{repo} type:issue {query}",
                "per_page": min(limit, 10),
            },
        )
        return [
            {
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "labels": [lbl.get("name") for lbl in i.get("labels", [])],
                "created_at": i.get("created_at"),
                "html_url": i.get("html_url"),
            }
            for i in items
        ]

    def search_pull_requests(
        self, owner: str, repo: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        items = self._request_items(
            "GET",
            "/search/issues",
            params={
                "q": f"repo:{owner}/{repo} type:pr {query}",
                "per_page": min(limit, 10),
            },
        )
        return [
            {
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "created_at": i.get("created_at"),
                "html_url": i.get("html_url"),
            }
            for i in items
        ]

    # ---------------- write tools (approval-gated at a higher layer) ----------------
    def add_issue_label(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> dict[str, Any]:
        data = self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )
        return {
            "applied": [label.get("name") for label in data],
            "count": len(data),
        }

    def add_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        data = self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        return {
            "comment_id": data.get("id"),
            "html_url": data.get("html_url"),
        }