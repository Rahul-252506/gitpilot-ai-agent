"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import AnalysisForm from "@/components/AnalysisForm";
import AgentTimeline from "@/components/AgentTimeline";
import ApprovalPanel from "@/components/ApprovalPanel";
import HistoryList from "@/components/HistoryList";
import ResolutionReport from "@/components/ResolutionReport";
import {
  ApiError,
  API_BASE_URL,
  approve,
  getAnalysis,
  health,
  isActive,
  listAnalyses,
  reject,
  startAnalysis,
} from "@/lib/api";
import type { AnalysisDetail, Approval, AnalysisListItem } from "@/lib/types";

const POLL_INTERVAL_MS = 1400;

function statusPill(status: string): string {
  return status.replace("_", " ");
}

export default function Home() {
  const [current, setCurrent] = useState<AnalysisDetail | null>(null);
  const [phase, setPhase] = useState<"idle" | "running">("idle");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [history, setHistory] = useState<AnalysisListItem[]>([]);
  const [online, setOnline] = useState<boolean | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const list = await listAnalyses(10);
      setHistory(list.items);
    } catch {
      // History is best-effort; ignore transient failures.
    }
  }, []);

  const fetchDetail = useCallback(async (analysisId: string) => {
    const detail = await getAnalysis(analysisId);
    setCurrent(detail);
    return detail;
  }, []);

  const poll = useCallback(
    (analysisId: string) => {
      stopPolling();
      const tick = async () => {
        try {
          const detail = await getAnalysis(analysisId);
          setCurrent(detail);
          if (isActive(detail.status)) {
            timerRef.current = setTimeout(() => tick(), POLL_INTERVAL_MS);
          } else {
            setPhase("idle");
            setNotice(null);
            refreshHistory();
          }
        } catch (err) {
          setError(
            err instanceof ApiError
              ? err.message
              : "Failed to fetch the analysis state."
          );
          setPhase("idle");
        }
      };
      tick();
    },
    [refreshHistory, stopPolling]
  );

  // Initial load: backend health + history.
  useEffect(() => {
    let cancelled = false;
    health()
      .then(() => !cancelled && setOnline(true))
      .catch(() => !cancelled && setOnline(false));
    refreshHistory();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [refreshHistory, stopPolling]);

  const handleStart = async (repository: string, issueNumber: number) => {
    setError(null);
    setNotice(null);
    setCurrent(null);
    setPhase("running");
    try {
      const result = await startAnalysis(repository, issueNumber);
      setNotice(`Analysis ${result.analysis_id} started — watching the agent work…`);
      poll(result.analysis_id);
    } catch (err) {
      setPhase("idle");
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to start the analysis."
      );
    }
  };

  const handleSelect = async (analysisId: string) => {
    setError(null);
    setNotice(null);
    try {
      const detail = await fetchDetail(analysisId);
      if (isActive(detail.status)) {
        setPhase("running");
        poll(analysisId);
      } else {
        setPhase("idle");
      }
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load the analysis."
      );
    }
  };

  const handleDecision = async (
    approval: Approval,
    action: "approve" | "reject"
  ) => {
    if (!current) return;
    setApprovalBusy(true);
    setError(null);
    try {
      if (action === "approve") {
        await approve(current.analysis_id, approval.id);
        setNotice(`Approved and executed: ${approval.action_type}.`);
      } else {
        await reject(current.analysis_id, approval.id);
        setNotice(`Rejected: ${approval.action_type}. No write was performed.`);
      }
      await fetchDetail(current.analysis_id);
      refreshHistory();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : `Failed to ${action} the proposed action.`
      );
    } finally {
      setApprovalBusy(false);
    }
  };

  return (
    <div className="container">
      <header className="header">
        <div>
          <h1>
            <span className="logo">GitPilot</span> — AI GitHub Issue Resolution
          </h1>
          <p>
            An AI agent investigates a GitHub issue with tools, gathers
            repository evidence, and produces a structured resolution report.
          </p>
        </div>
        <span className={`badge ${online === false ? "offline" : "online"}`}>
          {online === null
            ? "checking backend…"
            : online
              ? `backend online · ${API_BASE_URL}`
              : `backend offline · ${API_BASE_URL}`}
        </span>
      </header>

      {error && <div className="banner">✕ {error}</div>}
      {notice && <div className="banner warn">{notice}</div>}

      <div className="layout">
        <aside>
          <div className="card">
            <h2>Start analysis</h2>
            <AnalysisForm
              onSubmit={handleStart}
              busy={phase === "running"}
              offline={online === false}
              checking={online === null}
            />
          </div>
          <div className="card">
            <h2>Recent analyses</h2>
            <HistoryList
              items={history}
              activeId={current?.analysis_id ?? null}
              onSelect={handleSelect}
            />
          </div>
        </aside>

        <main>
          {current ? (
            <>
              <div className="card">
                <div className="status-row">
                  <div>
                    <span className="mono-file">{current.repository}</span>{" "}
                    <span className="mono-file">#{current.issue_number}</span>
                  </div>
                  <span className={`pill ${current.status}`}>
                    <span className="dot" />
                    {statusPill(current.status)}
                  </span>
                </div>

                <h2>Agent timeline</h2>
                <AgentTimeline
                  events={current.events}
                  status={current.status}
                />

                {current.approvals.length > 0 && (
                  <>
                    <h2 style={{ marginTop: 22 }}>
                      {current.approvals.some((a) => a.status === "pending")
                        ? "Proposed write actions — approval required"
                        : "Proposed write actions"}
                    </h2>
                    <ApprovalPanel
                      approvals={current.approvals}
                      onApprove={(a) => handleDecision(a, "approve")}
                      onReject={(a) => handleDecision(a, "reject")}
                      busy={approvalBusy}
                    />
                  </>
                )}
              </div>

              {current.report && (
                <div className="card">
                  <h2>Resolution report</h2>
                  <ResolutionReport
                    report={current.report}
                    repository={current.repository}
                    issueNumber={current.issue_number}
                  />
                </div>
              )}

              {current.status === "failed" && current.error_message && (
                <div className="banner">
                  ✕ Analysis failed: {current.error_message}
                </div>
              )}
            </>
          ) : (
            <div className="card">
              <h2>How it works</h2>
              <p>
                Enter a public GitHub repository (owner/repository) and an issue
                number. GitPilot will:
              </p>
              <ol className="clean">
                <li>Retrieve the issue and its context</li>
                <li>
                  Decide which tools it needs: repository search, file
                  inspection, related issues/PRs
                </li>
                <li>
                  Gather evidence within safety limits (step budget, timeout,
                  bounded output)
                </li>
                <li>
                  Produce a validated, structured resolution report with root
                  cause, affected files, and a test plan
                </li>
                <li>
                  Propose any GitHub write actions (labels/comments) only for
                  your explicit approval
                </li>
              </ol>
              <p className="meta">
                Configure with{" "}
                <span className="mono">GITHUB_TOKEN</span>,{" "}
                <span className="mono">LLM_PROVIDER=gemini</span> and{" "}
                <span className="mono">GEMINI_API_KEY</span>. See the README.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
