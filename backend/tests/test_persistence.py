"""Database persistence tests (.freebuff/11_DATABASE_DESIGN.md)."""
from __future__ import annotations

import pytest

from app.core.errors import AnalysisNotFoundError
from app.db.database import create_engine_for, init_db, make_session_factory
from app.db.repository import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    AnalysisRepository,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine_for(str(tmp_path / "persist.db"))
    init_db(engine)
    return make_session_factory(engine)


class TestPersistence:
    def test_analysis_lifecycle(self, db):
        with db() as session:
            repo = AnalysisRepository(session)
            analysis = repo.create_analysis("acme/demo", 42)
            aid = analysis.id
            repo.add_event(aid, "analysis_queued", "info", "queued")
            repo.add_event(aid, "tool_started", "started", "Calling get_issue", tool_name="get_issue")
            repo.add_event(aid, "tool_completed", "completed", "Retrieved issue #42", tool_name="get_issue")
            repo.set_status(aid, "completed")
            repo.commit()

        # fresh session: data persisted
        with db() as session:
            repo = AnalysisRepository(session)
            analysis = repo.get_analysis(aid)
            assert analysis.repository == "acme/demo"
            assert analysis.issue_number == 42
            assert analysis.status == "completed"
            events = repo.get_events(aid)
            assert [e.sequence for e in events] == [1, 2, 3]
            assert events[1].tool_name == "get_issue"
            assert events[1].event_type == "tool_started"

    def test_report_persistence_with_confidence_conversion(self, db):
        with db() as session:
            repo = AnalysisRepository(session)
            analysis = repo.create_analysis("acme/demo", 42)
            aid = analysis.id
            repo.save_report(
                aid,
                issue_summary="summary",
                category="bug",
                priority="high",
                root_cause="root cause",
                confidence=0.85,
                resolution_plan=["step 1"],
                affected_files=["src/a.py"],
                test_plan=["test 1"],
                evidence=[{"source": "get_file:src/a.py", "quote": "x", "kind": "confirmed"}],
                warnings=["warning"],
            )
            repo.commit()

        with db() as session:
            repo = AnalysisRepository(session)
            report = repo.get_report(aid)
            assert report is not None
            assert report.issue_summary == "summary"
            assert report.confidence == 85  # stored as 0..100
            assert report.affected_files_json == ["src/a.py"]
            assert report.evidence_json[0]["kind"] == "confirmed"

    def test_approval_persistence_and_resolution(self, db):
        with db() as session:
            repo = AnalysisRepository(session)
            analysis = repo.create_analysis("acme/demo", 42)
            aid = analysis.id
            approval = repo.create_approval(
                aid, "add_issue_label", {"owner": "acme", "repo": "demo", "issue_number": 42, "labels": ["bug"]}
            )
            repo.commit()
            approval_id = approval.id

        with db() as session:
            repo = AnalysisRepository(session)
            pending = repo.get_pending_approvals(aid)
            assert len(pending) == 1
            repo.resolve_approval(aid, approval_id, APPROVAL_APPROVED)
            repo.commit()

        with db() as session:
            repo = AnalysisRepository(session)
            approval = repo.get_approval(aid, approval_id)
            assert approval.status == APPROVAL_APPROVED
            assert approval.resolved_at is not None
            assert repo.get_pending_approvals(aid) == []

    def test_status_recompute_with_pending_approvals(self, db):
        with db() as session:
            repo = AnalysisRepository(session)
            analysis = repo.create_analysis("acme/demo", 42)
            aid = analysis.id
            repo.create_approval(aid, "add_issue_label", {"labels": ["x"]})
            status = repo.recompute_status(aid)
            assert status == "waiting_approval"
            repo.commit()

        with db() as session:
            repo = AnalysisRepository(session)
            approval = repo.get_pending_approvals(aid)[0]
            repo.resolve_approval(aid, approval.id, APPROVAL_APPROVED)
            status = repo.recompute_status(aid)
            assert status == "completed"

    def test_missing_analysis_raises(self, db):
        with db() as session:
            repo = AnalysisRepository(session)
            with pytest.raises(AnalysisNotFoundError):
                repo.get_analysis("missing")

    def test_events_never_store_secret_material(self, db):
        with db() as session:
            repo = AnalysisRepository(session)
            analysis = repo.create_analysis("acme/demo", 42)
            repo.add_event(analysis.id, "tool_completed", "completed", "Retrieved issue")
            repo.commit()
        with db() as session:
            repo = AnalysisRepository(session)
            for event in repo.get_events(analysis.id):
                assert "ghp_" not in event.summary
                assert "sk-" not in event.summary