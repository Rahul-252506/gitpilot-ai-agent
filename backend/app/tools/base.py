"""Tool abstractions: typed input, bounded output, structured errors."""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from app.services.llm.base import ToolSpec


class ToolResult(BaseModel):
    """Result of executing a tool.

    ``ok`` is always True unless the tool itself reports a recoverable
    failure. Exceptions raised by the handler are captured by the registry
    and converted into a failed ToolResult — they never propagate into the
    agent loop.
    """

    ok: bool = True
    summary: str = Field(description="Safe one-line status for the timeline")
    text: str = Field(
        default="", description="Bounded tool output shown to the model"
    )
    error: str | None = Field(
        default=None, description="Structured error summary (never a secret)"
    )
    pending_approval: bool = Field(
        default=False,
        description="True when a write action was proposed instead of executed",
    )
    fatal: bool = Field(
        default=False,
        description="True when the failure prevents any further progress",
    )


class ToolError(Exception):
    """Raised by tool handlers to report a recoverable failure.

    The orchestrator records the tool as failed and the agent may continue
    (non-critical failure strategy from .freebuff/09_WORKFLOW_ORCHESTRATION.md).
    """

    def __init__(self, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.fatal = fatal


class Tool(BaseModel):
    """A registered tool: name, description, JSON schema, and handler."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    is_write: bool = False
    handler: Callable[[dict[str, Any]], ToolResult]
    timeout_seconds: float = 20.0

    def to_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )