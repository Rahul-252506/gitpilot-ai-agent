"""Pydantic request/response models for the REST API (.freebuff/10_API_CONTRACTS.md)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.resolution import EvidenceItem, ProposedAction


# ---------------- Requests ----------------
class AnalysisStartRequest(BaseModel):
    repository: str = Field(description="GitHub repository in 'owner/repository' form")
    issue_number: int = Field(gt=0, description="Positive GitHub issue number")


class ApprovalDecisionRequest(BaseModel):
    approval_id: str | None = Field(
        default=None,
        description="Optional approval id; defaults to the first pending approval",
    )


# ---------------- Responses ----------------
class AnalysisStartResponse(BaseModel):
    analysis_id: str
    status: str


class ExecutionEventResponse(BaseModel):
    sequence: int
    event_type: str
    tool_name: str | None = None
    status: str
    summary: str
    created_at: datetime


class ReportResponse(BaseModel):
    issue_summary: str
    category: str
    priority: str
    root_cause: str
    evidence: list[EvidenceItem]
    affected_files: list[str]
    resolution_steps: list[str]
    test_plan: list[str]
    confidence: float
    warnings: list[str]
    proposed_actions: list[ProposedAction] = []


class ApprovalResponse(BaseModel):
    id: str
    action_type: str
    payload: dict
    rationale: str = ""
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    error_message: str | None = None


class ApprovalDecisionResponse(BaseModel):
    analysis_id: str
    approval_id: str
    status: str
    error_message: str | None = None


class AnalysisDetailResponse(BaseModel):
    analysis_id: str
    repository: str
    issue_number: int
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    events: list[ExecutionEventResponse] = []
    report: ReportResponse | None = None
    approvals: list[ApprovalResponse] = []


class AnalysisListItem(BaseModel):
    analysis_id: str
    repository: str
    issue_number: int
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None


class AnalysisListResponse(BaseModel):
    items: list[AnalysisListItem]
    total: int


class HealthResponse(BaseModel):
    status: str = "ok"
    # "demo" when the backend runs the deterministic demo fixture
    # (LLM_PROVIDER=demo); lets the UI label Demo Mode explicitly.
    mode: str = "live"


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail