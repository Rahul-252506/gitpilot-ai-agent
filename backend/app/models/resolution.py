"""Structured resolution report model (.freebuff/12_PROMPT_DESIGN.md).

The LLM's final answer must validate against this schema before it is
accepted and persisted.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EvidenceItem(BaseModel):
    """A single piece of evidence gathered during the investigation.

    ``kind`` distinguishes confirmed repository evidence (an actual tool
    result) from hypotheses/inference.
    """

    source: str = Field(description="Tool or location the evidence came from, e.g. 'get_file:src/auth.py'")
    quote: str = Field(description="Short verbatim excerpt or precise description of the evidence")
    kind: Literal["confirmed", "hypothesis"] = Field(
        description="'confirmed' = observed in repository/tool output; 'hypothesis' = inference"
    )


class ProposedAction(BaseModel):
    """A GitHub write action proposed by the agent (requires approval)."""

    action_type: Literal["add_issue_label", "add_issue_comment"]
    payload: dict = Field(
        description="Tool arguments, e.g. {'labels': ['bug']} or {'body': '...'}"
    )
    rationale: str = Field(default="", description="Short reason the action is proposed")


class ResolutionReport(BaseModel):
    """Validated final output of an analysis."""

    issue_summary: str = Field(min_length=1, description="Concise summary of the issue")
    category: str = Field(min_length=1, description="Issue category, e.g. 'bug', 'feature', 'refactor', 'docs'")
    priority: str = Field(
        min_length=1, description="One of: critical, high, medium, low, unknown"
    )
    root_cause: str = Field(min_length=1, description="Likely root cause with evidence")
    evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Confirmed evidence and clearly-labeled hypotheses",
    )
    affected_files: list[str] = Field(
        default_factory=list, description="Repository files implicated by the issue"
    )
    resolution_steps: list[str] = Field(
        default_factory=list, description="Recommended steps to resolve the issue"
    )
    test_plan: list[str] = Field(
        default_factory=list, description="How to verify the fix"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="0..1 confidence in the root cause"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Limitations, uncertainties, or actions that require care",
    )
    proposed_actions: list[ProposedAction] = Field(
        default_factory=list,
        description="Optional GitHub write actions that require explicit user approval",
    )

    @field_validator("affected_files", "resolution_steps", "test_plan")
    @classmethod
    def _not_empty_strings(cls, v: list[str]) -> list[str]:
        cleaned = [item.strip() for item in v if item and item.strip()]
        return cleaned

    @field_validator("priority")
    @classmethod
    def _normalize_priority(cls, v: str) -> str:
        normalized = v.strip().lower()
        allowed = {"critical", "high", "medium", "low", "unknown"}
        return normalized if normalized in allowed else "unknown"


class ResolutionReportWithExtras(ResolutionReport):
    """Report plus the evidence gathered during execution for the timeline."""

    pass