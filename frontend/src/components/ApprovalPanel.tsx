"use client";

import type { Approval } from "@/lib/types";

interface ApprovalPanelProps {
  approvals: Approval[];
  onApprove: (approval: Approval) => void;
  onReject: (approval: Approval) => void;
  busy: boolean;
}

function describeAction(approval: Approval): string {
  const p = approval.payload as Record<string, unknown>;
  const target = p && typeof p === "object"
    ? `${p.owner ?? "?"}/${p.repo ?? "?"}#${p.issue_number ?? "?"}`
    : "target issue";
  if (approval.action_type === "add_issue_label") {
    const labels = Array.isArray(p.labels) ? p.labels.join(", ") : "?";
    return `Add label${Array.isArray(p.labels) && p.labels.length !== 1 ? "s" : ""} ${labels} to ${target}`;
  }
  if (approval.action_type === "add_issue_comment") {
    return `Post a comment on ${target}`;
  }
  return `${approval.action_type} on ${target}`;
}

export default function ApprovalPanel({
  approvals,
  onApprove,
  onReject,
  busy,
}: ApprovalPanelProps) {
  if (!approvals.length) return null;
  const pending = approvals.filter((a) => a.status === "pending");
  const resolved = approvals.filter((a) => a.status !== "pending");

  return (
    <div>
      {pending.length > 0 && (
        <p className="approval-note">
          The agent proposed GitHub write actions below. Nothing is written to
          GitHub until you explicitly approve an action.
        </p>
      )}

      {approvals.map((approval) => (
        <div
          key={approval.id}
          className={`approval ${approval.status === "pending" ? "pending" : "resolved " + approval.status}`}
        >
          <div className="approval-head">
            <span className={`pill ${approval.status}`} style={{ padding: "1px 8px" }}>
              {approval.status}
            </span>
            <span className="action">{describeAction(approval)}</span>
          </div>
          {approval.rationale && (
            <div className="meta" style={{ marginBottom: 6 }}>
              Why: {approval.rationale}
            </div>
          )}
          <pre>{JSON.stringify(approval.payload, null, 2)}</pre>
          {approval.status === "pending" ? (
            <div className="approval-buttons">
              <button
                className="approve"
                onClick={() => onApprove(approval)}
                disabled={busy}
              >
                Approve &amp; execute
              </button>
              <button
                className="reject"
                onClick={() => onReject(approval)}
                disabled={busy}
              >
                Reject
              </button>
            </div>
          ) : (
            <div className="meta">
              {approval.status === "approved"
                ? "Executed on GitHub."
                : approval.status === "rejected"
                  ? "Skipped — no write was performed."
                  : `Failed: ${approval.error_message ?? "unknown error"}`}
            </div>
          )}
        </div>
      ))}

      {resolved.length === 0 && null}
    </div>
  );
}
