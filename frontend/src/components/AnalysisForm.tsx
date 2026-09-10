"use client";

import { useState } from "react";

interface AnalysisFormProps {
  onSubmit: (repository: string, issueNumber: number) => void;
  busy: boolean;
  offline: boolean;
  checking: boolean;
}

export default function AnalysisForm({
  onSubmit,
  busy,
  offline,
  checking,
}: AnalysisFormProps) {
  const [repository, setRepository] = useState("");
  const [issueNumber, setIssueNumber] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const trimmed = repository.trim().replace(/\/+$/, "");
    const repoRe = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
    if (!repoRe.test(trimmed)) {
      setError("Repository must be in owner/repository form, e.g. facebook/react");
      return;
    }
    const number = Number(issueNumber);
    if (!Number.isInteger(number) || number < 1) {
      setError("Issue number must be a positive integer");
      return;
    }
    onSubmit(trimmed, number);
  };

  return (
    <form onSubmit={handleSubmit}>
      <div className="form-row">
        <div className="field">
          <label htmlFor="repository">Repository</label>
          <input
            id="repository"
            type="text"
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            placeholder="owner/repository"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
        </div>
        <div className="field" style={{ flex: "0 0 150px" }}>
          <label htmlFor="issue">Issue #</label>
          <input
            id="issue"
            type="number"
            min={1}
            step={1}
            value={issueNumber}
            onChange={(e) => setIssueNumber(e.target.value)}
            placeholder="e.g. 42"
          />
        </div>
        <div
          className="field"
          style={{ flex: "0 0 auto", justifyContent: "flex-end" }}
        >
          <button
            type="submit"
            className="primary"
            disabled={busy || offline || checking}
          >
            {busy ? (
              <>
                <span className="spinner" /> Analyzing…
              </>
            ) : checking ? (
              "Checking backend…"
            ) : offline ? (
              "Backend offline"
            ) : (
              "Analyze issue"
            )}
          </button>
        </div>
      </div>
      {error && <div className="field-error">⚠ {error}</div>}
    </form>
  );
}
