"""Tests for input validation (.freebuff/14_TESTING_AND_VALIDATION.md)."""
from __future__ import annotations

import pytest

from app.core.errors import InvalidIssueNumberError, RepositoryNotFoundError
from app.core.validation import validate_issue_number, validate_repository


class TestRepositoryValidation:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("acme/demo", ("acme", "demo")),
            ("acme/demo/", ("acme", "demo")),
            ("  acme/repo-name  ", ("acme", "repo-name")),
            ("Org-1/repo_2", ("Org-1", "repo_2")),
            ("a/b.c", ("a", "b.c")),
        ],
    )
    def test_valid(self, value, expected):
        assert validate_repository(value) == expected

    @pytest.mark.parametrize(
        "value",
        ["", "acme", "acme/", "/demo", "ac me/demo", "acme/de mo", "acme//demo", None, 42],
    )
    def test_invalid(self, value):
        with pytest.raises(RepositoryNotFoundError):
            validate_repository(value)


class TestIssueNumberValidation:
    @pytest.mark.parametrize("value", [1, 42, 9999, "7"])
    def test_valid(self, value):
        assert validate_issue_number(value) == int(value)

    @pytest.mark.parametrize("value", [0, -1, "abc", None, 1.5, ""])
    def test_invalid(self, value):
        with pytest.raises(InvalidIssueNumberError):
            validate_issue_number(value)