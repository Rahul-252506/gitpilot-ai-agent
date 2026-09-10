"""Typed error hierarchy for GitPilot.

All error types inherit from GitPilotError so the API layer can translate
them into consistent JSON error responses without leaking internals.
"""
from __future__ import annotations


class GitPilotError(Exception):
    """Base class for all GitPilot application errors."""

    status_code: int = 400
    code: str = "gitpilot_error"

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


# ---------- Validation ----------
class ValidationError(GitPilotError):
    code = "validation_error"
    status_code = 422


class RepositoryNotFoundError(ValidationError):
    code = "repository_not_found"


class InvalidIssueNumberError(ValidationError):
    code = "invalid_issue_number"


# ---------- GitHub ----------
class GitHubError(GitPilotError):
    code = "github_error"
    status_code = 502


class GitHubAuthError(GitHubError):
    code = "github_auth_error"
    status_code = 502


class GitHubNotFoundError(GitHubError):
    code = "github_not_found"
    status_code = 404


class GitHubRateLimitError(GitHubError):
    code = "github_rate_limit"
    status_code = 429


class GitHubTimeoutError(GitHubError):
    code = "github_timeout"
    status_code = 504


class GitHubNetworkError(GitHubError):
    code = "github_network_error"
    status_code = 502


# ---------- LLM ----------
class LLMError(GitPilotError):
    code = "llm_error"
    status_code = 502


class LLMConfigurationError(LLMError):
    code = "llm_configuration_error"
    status_code = 500


class StructuredOutputError(GitPilotError):
    code = "structured_output_invalid"
    status_code = 500


# ---------- Agent ----------
class AgentError(GitPilotError):
    code = "agent_error"
    status_code = 500


class AgentStepLimitError(AgentError):
    code = "agent_step_limit"


class AgentTimeoutError(AgentError):
    code = "agent_timeout"


# ---------- Analysis / API ----------
class AnalysisNotFoundError(GitPilotError):
    code = "analysis_not_found"
    status_code = 404


class ApprovalNotFoundError(GitPilotError):
    code = "approval_not_found"
    status_code = 404


class ApprovalStateError(GitPilotError):
    code = "approval_not_pending"
    status_code = 409


class AnalysisStateError(GitPilotError):
    code = "analysis_state_error"
    status_code = 409