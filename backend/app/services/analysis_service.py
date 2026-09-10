"""Analysis service: starts runs, persists results, executes approvals.

Long-running agent work is executed in a background thread so the HTTP
request that starts an analysis returns immediately (API rule:
"Keep long-running work out of a blocking request when practical").
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agent.orchestrator import (
    EVENT_APPROVAL_PROPOSED,
    AgentOrchestrator,
)
from app.core.config import Settings
from app.core.errors import (
    AnalysisNotFoundError,
    ApprovalNotFoundError,
    ApprovalStateError,
    GitHubError,
    ValidationError,
)
from app.core.validation import validate_issue_number, validate_repository
from app.db.repository import (
    APPROVAL_APPROVED,
    APPROVAL_FAILED,
    APPROVAL_REJECTED,
    EVENT_ANALYSIS_COMPLETED,
    EVENT_ANALYSIS_FAILED,
    EVENT_APPROVAL_RESOLVED,
    EVENT_REPORT_GENERATED,
    EVENT_WRITE_EXECUTED,
    AnalysisRepository,
)
from app.models.resolution import ProposedAction, ResolutionReport
from app.schemas.api import (
    AnalysisDetailResponse,
    AnalysisListItem,
    AnalysisListResponse,
    ApprovalResponse,
    ExecutionEventResponse,
    ReportResponse,
)
from app.services.github_service import GitHubService
from app.services.llm.base import LLMProvider
from app.tools.github_tools import build_github_tools
from app.tools.registry import ToolRegistry

logger = logging.getLogger("gitpilot")


class AnalysisService:
    def __init__(
        self,
        session_factory,
        github: GitHubService,
        provider: LLMProvider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._github = github
        self._provider = provider
        self._settings = settings

    # ---------------- session helpers ----------------
    def _repo(self, session: Session) -> AnalysisRepository:
        return AnalysisRepository(session)

    # ---------------- start / run ----------------
    def start_analysis(self, repository: str, issue_number: int) -> str:
        owner, repo = validate_repository(repository)
        number = validate_issue_number(issue_number)
        with self._session_factory() as session:
            repo_ = self._repo(session)
            analysis = repo_.create_analysis(f"{owner}/{repo}", number)
            repo_.add_event(
                analysis.id,
                "analysis_queued",
                "info",
                f"Analysis queued for {owner}/{repo} issue #{number}",
            )
            repo_.commit()
            analysis_id = analysis.id
        return analysis_id

    def run_analysis(self, analysis_id: str) -> None:
        """Execute the full agent run for an analysis (blocking).

        Runs in the caller's thread (a background thread from the API layer,
        or synchronously from tests). Any unexpected exception is converted
        into a clean failed analysis — a crash must never leave a run stuck
        in the "running" state.
        """
        try:
            self._run_analysis_inner(analysis_id)
        except Exception as exc:  # noqa: BLE001 — last-resort safety net
            logger.exception("Analysis %s crashed unexpectedly", analysis_id)
            try:
                with self._session_factory() as session:
                    repo_ = self._repo(session)
                    repo_.set_status(
                        analysis_id,
                        "failed",
                        error_message=f"Internal error during analysis: {type(exc).__name__}",
                        error_code="internal_error",
                    )
                    repo_.add_event(
                        analysis_id,
                        EVENT_ANALYSIS_FAILED,
                        "failed",
                        f"Analysis crashed: {type(exc).__name__}",
                    )
                    repo_.commit()
            except Exception:  # pragma: no cover — DB itself is broken
                logger.exception("Could not persist failure state for %s", analysis_id)

    def _run_analysis_inner(self, analysis_id: str) -> None:
        with self._session_factory() as session:
            repo_ = self._repo(session)
            analysis = repo_.get_analysis(analysis_id)
            repository = analysis.repository
            issue_number = analysis.issue_number
            repo_.set_status(analysis_id, "running")
            repo_.commit()

        def event_sink(event_type: str, status: str, summary: str, tool_name: str | None) -> None:
            with self._session_factory() as s:
                r = self._repo(s)
                r.add_event(analysis_id, event_type, status, summary, tool_name)
                r.commit()

        def approval_sink(action_type: str, payload: dict, rationale: str) -> str:
            with self._session_factory() as s:
                r = self._repo(s)
                approval = r.create_approval(analysis_id, action_type, payload)
                r.add_event(
                    analysis_id,
                    EVENT_APPROVAL_PROPOSED,
                    "pending",
                    f"Write action proposed: {action_type} (awaiting approval)",
                    tool_name=action_type,
                )
                r.commit()
                return approval.id

        registry = ToolRegistry(
            build_github_tools(self._github, self._settings.tool_max_output_chars),
            max_output_chars=self._settings.tool_max_output_chars,
        )
        orchestrator = AgentOrchestrator(
            self._provider,
            registry,
            max_steps=self._settings.agent_max_steps,
            timeout_seconds=self._settings.agent_timeout_seconds,
            structured_output_retries=self._settings.structured_output_retries,
            event_sink=event_sink,
            approval_sink=approval_sink,
        )
        outcome = orchestrator.run(repository, issue_number)

        with self._session_factory() as session:
            repo_ = self._repo(session)
            if outcome.completed and outcome.report is not None:
                report = outcome.report
                self._save_report(session, analysis_id, report)
                for action in report.proposed_actions:
                    repo_.create_approval(analysis_id, action.action_type, action.payload)
                    repo_.add_event(
                        analysis_id,
                        EVENT_APPROVAL_PROPOSED,
                        "pending",
                        f"Write action proposed: {action.action_type} (awaiting approval)",
                        tool_name=action.action_type,
                    )
                repo_.add_event(
                    analysis_id,
                    EVENT_REPORT_GENERATED,
                    "completed",
                    "Resolution report generated and validated",
                )
                final_status = repo_.recompute_status(analysis_id)
                repo_.add_event(
                    analysis_id,
                    EVENT_ANALYSIS_COMPLETED,
                    "completed",
                    (
                        "Analysis completed; awaiting approval of proposed write action(s)"
                        if final_status == "waiting_approval"
                        else "Analysis completed"
                    ),
                )
                repo_.commit()
            else:
                repo_.set_status(
                    analysis_id,
                    "failed",
                    error_message=outcome.error_message,
                    error_code=outcome.error_code,
                )
                if outcome.limit_kind == "steps":
                    repo_.add_event(
                        analysis_id,
                        "limit_reached",
                        "failed",
                        f"Step limit reached: {outcome.error_message}",
                    )
                elif outcome.limit_kind == "timeout":
                    repo_.add_event(
                        analysis_id,
                        "limit_reached",
                        "failed",
                        f"Timeout reached: {outcome.error_message}",
                    )
                else:
                    repo_.add_event(
                        analysis_id,
                        EVENT_ANALYSIS_FAILED,
                        "failed",
                        outcome.error_message or "Analysis failed",
                    )
                repo_.commit()

    def _save_report(
        self, session: Session, analysis_id: str, report: ResolutionReport
    ) -> None:
        repo_ = self._repo(session)
        repo_.save_report(
            analysis_id,
            issue_summary=report.issue_summary,
            category=report.category,
            priority=report.priority,
            root_cause=report.root_cause,
            confidence=report.confidence,
            resolution_plan=report.resolution_steps,
            affected_files=report.affected_files,
            test_plan=report.test_plan,
            evidence=[e.model_dump() for e in report.evidence],
            warnings=report.warnings,
        )

    # ---------------- reads ----------------
    def get_analysis(self, analysis_id: str) -> AnalysisDetailResponse:
        with self._session_factory() as session:
            repo_ = self._repo(session)
            analysis = repo_.get_analysis(analysis_id)
            events = repo_.get_events(analysis_id)
            report = repo_.get_report(analysis_id)
            approvals = repo_.get_approvals(analysis_id)
            return self._to_detail(analysis, events, report, approvals)

    def list_analyses(self, limit: int = 20, offset: int = 0) -> AnalysisListResponse:
        with self._session_factory() as session:
            repo_ = self._repo(session)
            analyses = repo_.list_analyses(limit=min(limit, 100), offset=max(offset, 0))
            total = repo_.count_analyses()
            return AnalysisListResponse(
                items=[self._to_list_item(a) for a in analyses],
                total=total,
            )

    def health(self) -> bool:
        try:
            with self._session_factory() as session:
                session.execute(__import__("sqlalchemy").text("SELECT 1"))
            return True
        except Exception:
            return False

    # ---------------- approvals ----------------
    def approve(self, analysis_id: str, approval_id: str | None) -> dict[str, Any]:
        with self._session_factory() as session:
            repo_ = self._repo(session)
            analysis = repo_.get_analysis(analysis_id)
            approval = self._resolve_target(session, analysis_id, approval_id)
            owner, repo = validate_repository(analysis.repository)
            number = validate_issue_number(analysis.issue_number)
            payload = approval.action_payload_json
            try:
                self._execute_write(owner, repo, number, approval.action_type, payload)
            except (GitHubError, ValidationError) as exc:
                approval = repo_.resolve_approval(
                    analysis_id, approval.id, APPROVAL_FAILED, error_message=str(exc)
                )
                repo_.add_event(
                    analysis_id,
                    EVENT_APPROVAL_RESOLVED,
                    "failed",
                    f"Approval {approval.action_type} failed: {exc}",
                    tool_name=approval.action_type,
                )
                repo_.recompute_status(analysis_id)
                repo_.commit()
                return {"success": False, "approval_id": approval.id, "error": str(exc)}
            approval = repo_.resolve_approval(analysis_id, approval.id, APPROVAL_APPROVED)
            repo_.add_event(
                analysis_id,
                EVENT_WRITE_EXECUTED,
                "completed",
                f"Approved and executed {approval.action_type}",
                tool_name=approval.action_type,
            )
            repo_.recompute_status(analysis_id)
            repo_.commit()
            return {"success": True, "approval_id": approval.id, "error": None}

    def reject(self, analysis_id: str, approval_id: str | None) -> dict[str, Any]:
        with self._session_factory() as session:
            repo_ = self._repo(session)
            repo_.get_analysis(analysis_id)
            approval = self._resolve_target(session, analysis_id, approval_id)
            approval = repo_.resolve_approval(analysis_id, approval.id, APPROVAL_REJECTED)
            repo_.add_event(
                analysis_id,
                EVENT_APPROVAL_RESOLVED,
                "rejected",
                f"Write action {approval.action_type} rejected by user",
                tool_name=approval.action_type,
            )
            repo_.recompute_status(analysis_id)
            repo_.commit()
            return {"success": True, "approval_id": approval.id, "error": None}

    def _resolve_target(self, session: Session, analysis_id: str, approval_id: str | None):
        repo_ = self._repo(session)
        if approval_id:
            return repo_.get_approval(analysis_id, approval_id)
        pending = repo_.get_pending_approvals(analysis_id)
        if not pending:
            raise ApprovalStateError(f"No pending approvals for analysis {analysis_id}.")
        return pending[0]

    def _execute_write(
        self, owner: str, repo: str, issue_number: int, action_type: str, payload: dict
    ) -> None:
        """Perform the approved GitHub write using the server-side service."""
        if action_type == "add_issue_label":
            labels = payload.get("labels")
            if not isinstance(labels, list) or not labels:
                raise ValidationError("Approved action is missing 'labels'.")
            self._github.add_issue_label(owner, repo, issue_number, [str(l) for l in labels])
        elif action_type == "add_issue_comment":
            body = payload.get("body")
            if not isinstance(body, str) or not body.strip():
                raise ValidationError("Approved action is missing 'body'.")
            self._github.add_issue_comment(owner, repo, issue_number, body)
        else:
            raise ValidationError(f"Unknown approved action type: {action_type}")

    # ---------------- serialization ----------------
    def _to_list_item(self, analysis) -> AnalysisListItem:
        return AnalysisListItem(
            analysis_id=analysis.id,
            repository=analysis.repository,
            issue_number=analysis.issue_number,
            status=analysis.status,
            created_at=analysis.created_at,
            completed_at=analysis.completed_at,
            error_message=analysis.error_message,
        )

    def _to_detail(self, analysis, events, report, approvals) -> AnalysisDetailResponse:
        report_response = None
        if report is not None:
            report_response = ReportResponse(
                issue_summary=report.issue_summary,
                category=report.category,
                priority=report.priority,
                root_cause=report.root_cause,
                evidence=report.evidence_json or [],
                affected_files=report.affected_files_json or [],
                resolution_steps=report.resolution_plan_json or [],
                test_plan=report.test_plan_json or [],
                confidence=(report.confidence or 0) / 100.0,
                warnings=report.warnings_json or [],
                proposed_actions=self._proposed_actions_from_approvals(approvals),
            )
        return AnalysisDetailResponse(
            analysis_id=analysis.id,
            repository=analysis.repository,
            issue_number=analysis.issue_number,
            status=analysis.status,
            created_at=analysis.created_at,
            completed_at=analysis.completed_at,
            error_message=analysis.error_message,
            events=[
                ExecutionEventResponse(
                    sequence=e.sequence,
                    event_type=e.event_type,
                    tool_name=e.tool_name,
                    status=e.status,
                    summary=e.summary,
                    created_at=e.created_at,
                )
                for e in events
            ],
            report=report_response,
            approvals=[
                ApprovalResponse(
                    id=a.id,
                    action_type=a.action_type,
                    payload=a.action_payload_json,
                    rationale=a.action_payload_json.get("rationale", ""),
                    status=a.status,
                    created_at=a.created_at,
                    resolved_at=a.resolved_at,
                    error_message=a.error_message,
                )
                for a in approvals
            ],
        )

    @staticmethod
    def _proposed_actions_from_approvals(approvals) -> list[ProposedAction]:
        return [
            ProposedAction(
                action_type=a.action_type,
                payload=a.action_payload_json,
            )
            for a in approvals
        ]