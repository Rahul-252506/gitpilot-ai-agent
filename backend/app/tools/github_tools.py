"""GitHub tool implementations wrapping the GitHub service.

Each tool validates its arguments, bounds its output, and returns a
ToolResult. Write tools never execute: they only describe the action that
would be taken once the user approves it (the actual write is performed by
the approval layer using the GitHub service directly).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.validation import validate_issue_number, validate_repository
from app.services.github_service import GitHubService
from app.tools.base import Tool, ToolError, ToolResult
from app.tools.truncation import truncate, truncate_lines


# ---------------- argument models ----------------
class RepoArgs(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)

    def validated(self) -> tuple[str, str]:
        owner, repo = validate_repository(f"{self.owner}/{self.repo}")
        return owner, repo


class IssueArgs(RepoArgs):
    issue_number: int = Field(gt=0)


class SearchArgs(RepoArgs):
    query: str = Field(min_length=1, max_length=120)


class GetFileArgs(RepoArgs):
    path: str = Field(min_length=1, max_length=512)
    ref: str | None = Field(default=None, max_length=100)


class AddLabelArgs(IssueArgs):
    labels: list[str] = Field(min_length=1, max_length=10)

    def validated_labels(self) -> list[str]:
        cleaned = [lbl.strip() for lbl in self.labels if lbl.strip()]
        if not cleaned:
            raise ToolError("At least one non-empty label is required.")
        return cleaned[:10]


class AddCommentArgs(IssueArgs):
    body: str = Field(min_length=1, max_length=4000)


# ---------------- helpers ----------------
def _arg_error(exc: ValidationError) -> ToolResult:
    errors = "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
    )
    return ToolResult(
        ok=False,
        summary="Invalid tool arguments",
        text="",
        error=f"Invalid arguments for tool: {errors}",
    )


def _github_error(exc: Exception) -> ToolResult:
    # Convert any service error into a structured, recoverable tool failure.
    # The orchestrator decides whether the failure is fatal (it terminates
    # when the initial get_issue call fails). Search failures simply get
    # recorded and the agent may continue.
    return ToolResult(
        ok=False,
        summary="Tool failed",
        text="",
        error=str(exc),
    )


# ---------------- tool builders ----------------
def build_github_tools(
    github: GitHubService, max_output_chars: int = 8000
) -> list[Tool]:
    def _get_issue(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = IssueArgs(**args)
            owner, repo = parsed.validated()
            number = validate_issue_number(parsed.issue_number)
        except ValidationError as exc:
            return _arg_error(exc)
        except Exception as exc:
            return _github_error(exc)
        try:
            issue = github.get_issue(owner, repo, number)
        except Exception as exc:
            return _github_error(exc)
        labels = ", ".join(issue.get("labels") or []) or "none"
        body = truncate(issue.get("body") or "(no body)", max_output_chars // 2)
        comments = issue.get("comments") or []
        comment_lines = []
        for c in comments[:3]:
            comment_lines.append(
                f"- @{c.get('author')}: {truncate(c.get('body') or '', 300)}"
            )
        text = (
            f"Issue #{number} ({issue.get('state')}) by @{issue.get('author')}\n"
            f"Title: {issue.get('title')}\n"
            f"Labels: {labels}\n"
            f"Created: {issue.get('created_at')} | Updated: {issue.get('updated_at')}\n"
            f"Is PR: {issue.get('is_pull_request')}\n"
            f"Body:\n{body}\n"
            f"Recent comments ({issue.get('comments_count')} total):\n"
            + ("\n".join(comment_lines) if comment_lines else "(none)")
        )
        return ToolResult(
            summary=f"Retrieved issue #{number}: {issue.get('title')}",
            text=truncate(text, max_output_chars),
        )

    def _search_repository(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = SearchArgs(**args)
            owner, repo = parsed.validated()
        except ValidationError as exc:
            return _arg_error(exc)
        try:
            results = github.search_repository(owner, repo, parsed.query)
        except Exception as exc:
            return _github_error(exc)
        if not results:
            return ToolResult(
                summary=f"Repository search for {parsed.query!r}: no matches",
                text="No matching files found in the repository.",
            )
        lines = [f"Matches for {parsed.query!r} in {owner}/{repo}:"]
        for item in results:
            snippet = truncate(item.get("snippet") or "", 200)
            lines.append(f"- {item.get('path')}\n  {snippet}")
        text = "\n".join(lines)
        return ToolResult(
            summary=f"Repository search for {parsed.query!r}: {len(results)} file(s)",
            text=truncate(text, max_output_chars),
        )

    def _get_file(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = GetFileArgs(**args)
            owner, repo = parsed.validated()
        except ValidationError as exc:
            return _arg_error(exc)
        try:
            data = github.get_file(owner, repo, parsed.path, parsed.ref)
        except Exception as exc:
            return _github_error(exc)
        if data.get("type") == "directory":
            entries = data.get("entries") or []
            lines = [f"Directory {data.get('path')}:"] + [
                f"- {e.get('type')}: {e.get('name')}" for e in entries[:100]
            ]
            return ToolResult(
                summary=f"Listed directory {parsed.path} ({len(entries)} entries)",
                text=truncate("\n".join(lines), max_output_chars),
            )
        content = data.get("content") or ""
        bounded = truncate_lines(content, max_lines=250, max_chars=max_output_chars)
        text = f"File: {data.get('path')} ({data.get('size')} bytes)\n{bounded}"
        return ToolResult(
            summary=f"Inspected {parsed.path}",
            text=truncate(text, max_output_chars),
        )

    def _search_issues(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = SearchArgs(**args)
            owner, repo = parsed.validated()
        except ValidationError as exc:
            return _arg_error(exc)
        try:
            results = github.search_issues(owner, repo, parsed.query)
        except Exception as exc:
            return _github_error(exc)
        if not results:
            return ToolResult(
                summary=f"Issue search for {parsed.query!r}: no results",
                text="No related issues found.",
            )
        lines = [f"Related issues for {parsed.query!r}:"]
        for item in results:
            lines.append(
                f"- #{item.get('number')} [{item.get('state')}] "
                f"{item.get('title')} (labels: {', '.join(item.get('labels') or []) or 'none'})"
            )
        return ToolResult(
            summary=f"Found {len(results)} related issue(s)",
            text=truncate("\n".join(lines), max_output_chars),
        )

    def _search_pull_requests(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = SearchArgs(**args)
            owner, repo = parsed.validated()
        except ValidationError as exc:
            return _arg_error(exc)
        try:
            results = github.search_pull_requests(owner, repo, parsed.query)
        except Exception as exc:
            return _github_error(exc)
        if not results:
            return ToolResult(
                summary=f"PR search for {parsed.query!r}: no results",
                text="No related pull requests found.",
            )
        lines = [f"Related pull requests for {parsed.query!r}:"]
        for item in results:
            lines.append(f"- #{item.get('number')} [{item.get('state')}] {item.get('title')}")
        return ToolResult(
            summary=f"Found {len(results)} related pull request(s)",
            text=truncate("\n".join(lines), max_output_chars),
        )

    # Write tools: describe only, never execute.
    def _add_issue_label(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = AddLabelArgs(**args)
            owner, repo = parsed.validated()
            number = validate_issue_number(parsed.issue_number)
            labels = parsed.validated_labels()
        except ValidationError as exc:
            return _arg_error(exc)
        except Exception as exc:
            return _github_error(exc)
        return ToolResult(
            summary=f"Proposed adding label(s) {', '.join(labels)} to issue #{number}",
            text=(
                f"Write action proposed (requires approval): add label(s) "
                f"{', '.join(labels)} to {owner}/{repo} issue #{number}."
            ),
            pending_approval=True,
        )

    def _add_issue_comment(args: dict[str, Any]) -> ToolResult:
        try:
            parsed = AddCommentArgs(**args)
            owner, repo = parsed.validated()
            number = validate_issue_number(parsed.issue_number)
        except ValidationError as exc:
            return _arg_error(exc)
        except Exception as exc:
            return _github_error(exc)
        return ToolResult(
            summary=f"Proposed commenting on issue #{number}",
            text=(
                f"Write action proposed (requires approval): post a comment on "
                f"{owner}/{repo} issue #{number}."
            ),
            pending_approval=True,
        )

    def args_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"type": "object", "properties": properties, "required": required}

    owner_repo = {
        "owner": {"type": "string", "description": "GitHub owner or organization"},
        "repo": {"type": "string", "description": "Repository name"},
    }

    return [
        Tool(
            name="get_issue",
            description=(
                "Retrieve a GitHub issue by number: title, body, labels, state, "
                "author, and recent comments. Call this first for a new task."
            ),
            parameters=args_schema(
                {
                    **owner_repo,
                    "issue_number": {"type": "integer", "description": "GitHub issue number"},
                },
                ["owner", "repo", "issue_number"],
            ),
            handler=_get_issue,
        ),
        Tool(
            name="search_repository",
            description=(
                "Search repository source code for keywords/symbols from the issue. "
                "Returns matching file paths with snippets."
            ),
            parameters=args_schema(
                {**owner_repo, "query": {"type": "string", "description": "Search terms"}},
                ["owner", "repo", "query"],
            ),
            handler=_search_repository,
        ),
        Tool(
            name="get_file",
            description=(
                "Inspect a file's content by path (optionally at a ref/branch). "
                "Output is bounded."
            ),
            parameters=args_schema(
                {
                    **owner_repo,
                    "path": {"type": "string", "description": "File path in the repository"},
                    "ref": {"type": "string", "description": "Optional branch/commit/tag"},
                },
                ["owner", "repo", "path"],
            ),
            handler=_get_file,
        ),
        Tool(
            name="search_issues",
            description="Search related GitHub issues in the repository by query.",
            parameters=args_schema(
                {**owner_repo, "query": {"type": "string", "description": "Search terms"}},
                ["owner", "repo", "query"],
            ),
            handler=_search_issues,
        ),
        Tool(
            name="search_pull_requests",
            description="Search related pull requests in the repository by query.",
            parameters=args_schema(
                {**owner_repo, "query": {"type": "string", "description": "Search terms"}},
                ["owner", "repo", "query"],
            ),
            handler=_search_pull_requests,
        ),
        Tool(
            name="add_issue_label",
            description=(
                "Propose adding label(s) to the target issue. This is a WRITE action: "
                "it is only proposed and requires explicit user approval; nothing is "
                "written to GitHub until approved."
            ),
            parameters=args_schema(
                {
                    **owner_repo,
                    "issue_number": {"type": "integer"},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Labels to add",
                    },
                },
                ["owner", "repo", "issue_number", "labels"],
            ),
            is_write=True,
            handler=_add_issue_label,
        ),
        Tool(
            name="add_issue_comment",
            description=(
                "Propose posting a comment on the target issue. This is a WRITE action: "
                "it is only proposed and requires explicit user approval; nothing is "
                "written to GitHub until approved."
            ),
            parameters=args_schema(
                {
                    **owner_repo,
                    "issue_number": {"type": "integer"},
                    "body": {"type": "string", "description": "Comment body"},
                },
                ["owner", "repo", "issue_number", "body"],
            ),
            is_write=True,
            handler=_add_issue_comment,
        ),
    ]