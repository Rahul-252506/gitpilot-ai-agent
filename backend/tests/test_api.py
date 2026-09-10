"""REST API tests (.freebuff/10_API_CONTRACTS.md, .freebuff/14)."""
from __future__ import annotations

import pytest

from app.services.llm.mock_provider import (
    final_response,
    tool_call_response,
)

from tests.test_agent import FailingLLMProvider

REPO = "acme/demo"
ISSUE = 42


class TestHealth:
    def test_health(self, make_client, tmp_path):
        client = make_client(tmp_path)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestStartAnalysis:
    def test_happy_path_queued_then_completed(self, make_client, tmp_path, normal_script):
        client = make_client(tmp_path, script=list(normal_script))
        resp = client.post("/api/analyses", json={"repository": REPO, "issue_number": ISSUE})
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "queued"
        analysis_id = body["analysis_id"]

        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "completed"
        assert detail["repository"] == REPO
        assert detail["issue_number"] == ISSUE
        assert detail["report"] is not None
        report = detail["report"]
        assert report["issue_summary"]
        assert report["root_cause"]
        assert report["confidence"] == pytest.approx(0.85)
        assert report["affected_files"] == ["src/auth/token_manager.py"]
        # timeline shows tools
        tool_names = [e["tool_name"] for e in detail["events"]]
        assert "get_issue" in tool_names
        assert "search_repository" in tool_names
        assert "get_file" in tool_names

    @pytest.mark.parametrize(
        "payload",
        [
            {"repository": "not-a-repo", "issue_number": 1},
            {"repository": "", "issue_number": 1},
            {"repository": "acme/demo", "issue_number": 0},
            {"repository": "acme/demo", "issue_number": -4},
            {"repository": "acme", "issue_number": "x"},
            {"repository": 42, "issue_number": 1},
        ],
    )
    def test_invalid_requests(self, make_client, tmp_path, payload):
        client = make_client(tmp_path)
        resp = client.post("/api/analyses", json=payload)
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body
        assert "code" in body["detail"]

    def test_missing_fields(self, make_client, tmp_path):
        client = make_client(tmp_path)
        resp = client.post("/api/analyses", json={})
        assert resp.status_code == 422

    def test_failed_analysis_reports_error(self, make_client, tmp_path):
        script = [
            tool_call_response("get_issue", {"owner": "acme", "repo": "demo", "issue_number": 999})
        ]
        client = make_client(tmp_path, script=script)
        resp = client.post("/api/analyses", json={"repository": REPO, "issue_number": 999})
        analysis_id = resp.json()["analysis_id"]
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "failed"
        assert detail["error_message"]
        assert any(e["event_type"] == "tool_failed" for e in detail["events"])

    def test_llm_failure_fails_analysis_not_stuck_running(self, make_client, tmp_path):
        """A provider outage must end in a clean failed state — never a run
        stuck in 'running' with a crashed background worker."""
        client = make_client(tmp_path, provider=FailingLLMProvider())
        resp = client.post("/api/analyses", json={"repository": REPO, "issue_number": ISSUE})
        assert resp.status_code == 201
        analysis_id = resp.json()["analysis_id"]
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "failed"
        assert detail["error_message"]
        assert any(
            e["event_type"] == "analysis_failed" and "outage" in e["summary"].lower()
            for e in detail["events"]
        )


class TestGetAnalysis:
    def test_not_found(self, make_client, tmp_path):
        client = make_client(tmp_path)
        resp = client.get("/api/analyses/does_not_exist")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "analysis_not_found"

    def test_list_analyses(self, make_client, tmp_path, normal_script):
        client = make_client(tmp_path, script=list(normal_script))
        for _ in range(2):
            resp = client.post("/api/analyses", json={"repository": REPO, "issue_number": ISSUE})
            assert resp.status_code == 201
        resp = client.get("/api/analyses")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        item = body["items"][0]
        assert item["repository"] == REPO
        assert item["issue_number"] == ISSUE


class TestApprovalFlow:
    def _start_with_write_proposal(self, make_client, tmp_path):
        script = [
            tool_call_response("get_issue", {"owner": "acme", "repo": "demo", "issue_number": 42}),
            tool_call_response(
                "add_issue_label",
                {"owner": "acme", "repo": "demo", "issue_number": 42, "labels": ["bug"]},
            ),
            final_response({
                "issue_summary": "Issue investigated.",
                "category": "bug",
                "priority": "high",
                "root_cause": "Token not refreshed.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.8,
                "warnings": [],
            }),
        ]
        client = make_client(tmp_path, script=script)
        resp = client.post("/api/analyses", json={"repository": REPO, "issue_number": ISSUE})
        analysis_id = resp.json()["analysis_id"]
        return client, analysis_id

    def test_waiting_for_approval_then_approve_executes_write(self, make_client, tmp_path):
        client, analysis_id = self._start_with_write_proposal(make_client, tmp_path)
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "waiting_approval"
        assert len(detail["approvals"]) == 1
        approval = detail["approvals"][0]
        assert approval["status"] == "pending"
        assert approval["action_type"] == "add_issue_label"

        resp = client.post(f"/api/analyses/{analysis_id}/approve", json={"approval_id": approval["id"]})
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "completed"
        assert detail["approvals"][0]["status"] == "approved"
        assert any(e["event_type"] == "write_executed" for e in detail["events"])

    def test_reject_does_not_write(self, make_client, tmp_path):
        client, analysis_id = self._start_with_write_proposal(make_client, tmp_path)
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        approval_id = detail["approvals"][0]["id"]

        resp = client.post(f"/api/analyses/{analysis_id}/reject", json={"approval_id": approval_id})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "completed"
        assert detail["approvals"][0]["status"] == "rejected"
        assert not any(e["event_type"] == "write_executed" for e in detail["events"])

    def test_approve_twice_conflicts(self, make_client, tmp_path):
        client, analysis_id = self._start_with_write_proposal(make_client, tmp_path)
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        approval_id = detail["approvals"][0]["id"]
        client.post(f"/api/analyses/{analysis_id}/approve", json={"approval_id": approval_id})
        resp = client.post(f"/api/analyses/{analysis_id}/approve", json={"approval_id": approval_id})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "approval_not_pending"

    def test_approve_unknown_approval(self, make_client, tmp_path):
        client, analysis_id = self._start_with_write_proposal(make_client, tmp_path)
        resp = client.post(f"/api/analyses/{analysis_id}/approve", json={"approval_id": "nope"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "approval_not_found"

    def test_approve_missing_analysis(self, make_client, tmp_path):
        client = make_client(tmp_path)
        resp = client.post("/api/analyses/ghost/approve")
        assert resp.status_code == 404

    def test_report_proposed_action_creates_approval(self, make_client, tmp_path):
        script = [
            tool_call_response("get_issue", {"owner": "acme", "repo": "demo", "issue_number": 42}),
            final_response({
                "issue_summary": "Issue investigated.",
                "category": "bug",
                "priority": "high",
                "root_cause": "Token not refreshed.",
                "evidence": [],
                "affected_files": [],
                "resolution_steps": [],
                "test_plan": [],
                "confidence": 0.8,
                "warnings": [],
                "proposed_actions": [
                    {
                        "action_type": "add_issue_comment",
                        "payload": {"owner": "acme", "repo": "demo", "issue_number": 42, "body": "Root cause identified."},
                        "rationale": "Inform the reporter.",
                    }
                ],
            }),
        ]
        client = make_client(tmp_path, script=script)
        resp = client.post("/api/analyses", json={"repository": REPO, "issue_number": ISSUE})
        analysis_id = resp.json()["analysis_id"]
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "waiting_approval"
        assert detail["approvals"][0]["action_type"] == "add_issue_comment"
        assert detail["report"]["proposed_actions"][0]["action_type"] == "add_issue_comment"

        resp = client.post(f"/api/analyses/{analysis_id}/approve")
        assert resp.status_code == 200
        detail = client.get(f"/api/analyses/{analysis_id}").json()
        assert detail["approvals"][0]["status"] == "approved"
        assert any(e["event_type"] == "write_executed" for e in detail["events"])