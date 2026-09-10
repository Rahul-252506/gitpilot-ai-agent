"""Agent context: task identity, conversation, and step/limit tracking.

Context management rules from .freebuff/09_WORKFLOW_ORCHESTRATION.md:
- keep the task, repository/issue identity, bounded tool results, and
  previous actions
- avoid duplicate tool results, unbounded file contents, and secrets
"""
from __future__ import annotations

import time

from app.services.llm.base import LLMMessage


class AgentContext:
    """State kept by the orchestrator during one analysis run."""

    def __init__(
        self,
        repository: str,
        issue_number: int,
        max_steps: int,
        timeout_seconds: int,
    ) -> None:
        self.repository = repository
        self.issue_number = issue_number
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.started_at = time.monotonic()
        self.steps = 0
        self.output_retries = 0
        self.fatal_error: Exception | None = None
        self.messages: list[LLMMessage] = []

    @property
    def timed_out(self) -> bool:
        return time.monotonic() - self.started_at >= self.timeout_seconds

    @property
    def step_limit_reached(self) -> bool:
        return self.steps >= self.max_steps