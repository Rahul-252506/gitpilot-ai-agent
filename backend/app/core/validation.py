"""Shared input validation helpers."""
from __future__ import annotations

import re

from app.core.errors import InvalidIssueNumberError, RepositoryNotFoundError

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def validate_repository(repository: str) -> tuple[str, str]:
    """Validate an ``owner/repository`` string and return (owner, repo).

    Raises RepositoryNotFoundError (validation error) for malformed input.
    """
    if not repository or not isinstance(repository, str):
        raise RepositoryNotFoundError("Repository must be a non-empty string.")
    repository = repository.strip().strip("/")
    if "/" not in repository:
        raise RepositoryNotFoundError(
            f"Invalid repository format: {repository!r}. Expected 'owner/repository'."
        )
    owner, repo = repository.split("/", 1)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", repo
    ):
        raise RepositoryNotFoundError(
            f"Invalid repository format: {repository!r}. "
            "Owner and repository may only contain letters, digits, '-', '_', '.'."
        )
    return owner, repo


def validate_issue_number(issue_number: int | str) -> int:
    """Validate a positive integer GitHub issue number."""
    if isinstance(issue_number, bool):
        raise InvalidIssueNumberError(
            f"Invalid issue number: {issue_number!r}. Must be a positive integer."
        )
    if isinstance(issue_number, float) and not issue_number.is_integer():
        raise InvalidIssueNumberError(
            f"Invalid issue number: {issue_number!r}. Must be a positive integer."
        )
    try:
        value = int(issue_number)
    except (TypeError, ValueError):
        raise InvalidIssueNumberError(
            f"Invalid issue number: {issue_number!r}. Must be a positive integer."
        )
    if value < 1:
        raise InvalidIssueNumberError(
            f"Invalid issue number: {value}. Must be a positive integer."
        )
    return value