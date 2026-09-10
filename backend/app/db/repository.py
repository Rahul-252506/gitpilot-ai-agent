"""Data-access layer for analyses, events, reports, and approvals.

Only bounded summaries/results are stored (per .freebuff/11_DATABASE_DESIGN.md);
raw GitHub responses are never persisted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import (
    AnalysisNotFoundError,
    ApprovalNotFoundError,
    ApprovalStateError,
)
from app.models.db import Analysis, Approval, ExecutionEvent, ResolutionReport

# Analysis statuses (contract superset of queued|running|completed|failed)
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_WAITING_APPROVAL = "waiting_approval"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Approval statuses
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_FAILED = "failed"

# Event types
EVENT_ANALYSIS_QUEUED = "analysis_queued"
EVENT_ANALYSIS_STARTED = "analysis_started"
EVENT_TOOL_STARTED = "tool_started"
EVENT_TOOL_COMPLETED = "tool_completed"
EVENT_TOOL_FAILED = "tool_failed"
EVENT_STATUS = "status"
EVENT_APPROVAL_PROPOSED = "approval_proposed"
EVENT_APPROVAL_RESOLVED = "approval_resolved"
EVENT_WRITE_EXECUTED = "write_executed"
EVENT_REPORT_GENERATED = "report_generated"
EVENT_ANALYSIS_COMPLETED = "analysis_completed"
EVENT_ANALYSIS_FAILED = "analysis_failed"
EVENT_LIMIT_REACHED = "limit_reached"


def new_id(prefix: str = "anl") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------- analyses ----------------
    def create_analysis(self, repository: str, issue_number: int) -> Analysis:
        analysis = Analysis(
            id=new_id(),
            repository=repository,
            issue_number=issue_number,
            status=STATUS_QUEUED,
        )
        self.session.add(analysis)
        self.session.flush()
        return analysis

    def get_analysis(self, analysis_id: str) -> Analysis:
        analysis = self.session.get(Analysis, analysis_id)
        if analysis is None:
            raise AnalysisNotFoundError(f"Analysis {analysis_id} not found.")
        return analysis

    def list_analyses(self, limit: int = 20, offset: int = 0) -> list[Analysis]:
        stmt = (
            select(Analysis)
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all())

    def count_analyses(self) -> int:
        return int(self.session.scalar(select(func.count(Analysis.id))) or 0)

    def set_status(
        self,
        analysis_id: str,
        status: str,
        error_message: str | None = None,
        error_code: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        values: dict = {"status": status}
        if status in (STATUS_COMPLETED, STATUS_FAILED):
            values["completed_at"] = now
        if error_message is not None:
            values["error_message"] = error_message
        if error_code is not None:
            values["fatal_error_code"] = error_code
        self.session.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(**values)
        )

    def recompute_status(self, analysis_id: str) -> str:
        """Return 'waiting_approval' when pending approvals remain, else 'completed'."""
        pending = (
            self.session.scalar(
                select(func.count(Approval.id)).where(
                    Approval.analysis_id == analysis_id,
                    Approval.status == APPROVAL_PENDING,
                )
            )
            or 0
        )
        status = STATUS_WAITING_APPROVAL if pending > 0 else STATUS_COMPLETED
        self.set_status(analysis_id, status)
        return status

    # ---------------- events ----------------
    def add_event(
        self,
        analysis_id: str,
        event_type: str,
        status: str = "info",
        summary: str = "",
        tool_name: str | None = None,
    ) -> ExecutionEvent:
        max_seq = self.session.scalar(
            select(func.max(ExecutionEvent.sequence)).where(
                ExecutionEvent.analysis_id == analysis_id
            )
        )
        sequence = (max_seq or 0) + 1
        event = ExecutionEvent(
            analysis_id=analysis_id,
            sequence=sequence,
            event_type=event_type,
            status=status,
            summary=summary,
            tool_name=tool_name,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def get_events(self, analysis_id: str) -> list[ExecutionEvent]:
        return list(
            self.session.scalars(
                select(ExecutionEvent)
                .where(ExecutionEvent.analysis_id == analysis_id)
                .order_by(ExecutionEvent.sequence)
            ).all()
        )

    # ---------------- reports ----------------
    def save_report(
        self,
        analysis_id: str,
        *,
        issue_summary: str,
        category: str,
        priority: str,
        root_cause: str,
        confidence: float,
        resolution_plan: list[str],
        affected_files: list[str],
        test_plan: list[str],
        evidence: list[dict],
        warnings: list[str],
    ) -> ResolutionReport:
        report = ResolutionReport(
            analysis_id=analysis_id,
            issue_summary=issue_summary,
            category=category,
            priority=priority,
            root_cause=root_cause,
            confidence=int(round(max(0.0, min(1.0, confidence)) * 100)),
            resolution_plan_json=resolution_plan,
            affected_files_json=affected_files,
            test_plan_json=test_plan,
            evidence_json=evidence,
            warnings_json=warnings,
        )
        self.session.add(report)
        self.session.flush()
        return report

    def get_report(self, analysis_id: str) -> ResolutionReport | None:
        return self.session.scalar(
            select(ResolutionReport).where(
                ResolutionReport.analysis_id == analysis_id
            )
        )

    # ---------------- approvals ----------------
    def create_approval(
        self, analysis_id: str, action_type: str, payload: dict
    ) -> Approval:
        approval = Approval(
            id=new_id("appr"),
            analysis_id=analysis_id,
            action_type=action_type,
            action_payload_json=payload,
            status=APPROVAL_PENDING,
        )
        self.session.add(approval)
        self.session.flush()
        return approval

    def get_approval(self, analysis_id: str, approval_id: str) -> Approval:
        approval = self.session.get(Approval, approval_id)
        if approval is None or approval.analysis_id != analysis_id:
            raise ApprovalNotFoundError(
                f"Approval {approval_id} not found for analysis {analysis_id}."
            )
        return approval

    def get_pending_approvals(self, analysis_id: str) -> list[Approval]:
        return list(
            self.session.scalars(
                select(Approval)
                .where(
                    Approval.analysis_id == analysis_id,
                    Approval.status == APPROVAL_PENDING,
                )
                .order_by(Approval.created_at)
            ).all()
        )

    def get_approvals(self, analysis_id: str) -> list[Approval]:
        return list(
            self.session.scalars(
                select(Approval)
                .where(Approval.analysis_id == analysis_id)
                .order_by(Approval.created_at)
            ).all()
        )

    def resolve_approval(
        self,
        analysis_id: str,
        approval_id: str,
        status: str,
        error_message: str | None = None,
    ) -> Approval:
        approval = self.get_approval(analysis_id, approval_id)
        if approval.status != APPROVAL_PENDING:
            raise ApprovalStateError(
                f"Approval {approval_id} is already {approval.status}, not pending."
            )
        approval.status = status
        approval.resolved_at = datetime.now(timezone.utc)
        if error_message is not None:
            approval.error_message = error_message
        self.session.flush()
        return approval

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()