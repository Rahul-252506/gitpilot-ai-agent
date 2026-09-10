"use client";

import type { ResolutionReport as Report } from "@/lib/types";

interface ResolutionReportProps {
  report: Report;
  repository: string;
  issueNumber: number;
}

function List({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <div className="meta">{empty}</div>;
  return (
    <ul className="clean">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

export default function ResolutionReport({
  report,
  repository,
  issueNumber,
}: ResolutionReportProps) {
  const confidence = Math.round(report.confidence * 100);

  return (
    <div>
      {/* 1. Issue summary */}
      <section className="report-section">
        <div className="label">Issue summary</div>
        <p style={{ marginTop: 0 }}>
          #{issueNumber} in <span className="mono-file">{repository}</span>
        </p>
        <p style={{ marginTop: 0 }}>{report.issue_summary}</p>
      </section>

      {/* 2. Classification */}
      <section className="report-section">
        <div className="label">Classification</div>
        <div className="kv-grid">
          <div>
            <div className="meta">Category</div>
            <div className="priority">{report.category || "—"}</div>
          </div>
          <div>
            <div className="meta">Priority</div>
            <div className="priority">{report.priority || "—"}</div>
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <div className="meta">
            Confidence: {confidence}%
          </div>
          <div className="confidence-bar">
            <div
              className="confidence-fill"
              style={{ width: `${confidence}%` }}
            />
          </div>
        </div>
      </section>

      {/* 3. Root cause */}
      <section className="report-section">
        <div className="label">Root cause</div>
        <p style={{ marginTop: 4 }}>{report.root_cause}</p>
      </section>

      {/* Evidence */}
      {report.evidence.length > 0 && (
        <section className="report-section">
          <div className="label">Evidence</div>
          {report.evidence.map((ev, i) => (
            <div key={i} className="evidence-item">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span
                  className={`evidence-kind ${ev.kind === "confirmed" ? "confirmed" : "hypothesis"}`}
                >
                  {ev.kind}
                </span>
                <span className="evidence-source">{ev.source}</span>
              </div>
              <p className="quote">{ev.quote}</p>
            </div>
          ))}
        </section>
      )}

      {/* 4. Affected files */}
      <section className="report-section">
        <div className="label">Affected files</div>
        <div>
          {report.affected_files.length ? (
            report.affected_files.map((f, i) => (
              <span key={i} className="mono-file">
                {f}
              </span>
            ))
          ) : (
            <div className="meta">None identified</div>
          )}
        </div>
      </section>

      {/* 5. Resolution plan */}
      <section className="report-section">
        <div className="label">Resolution plan</div>
        <List items={report.resolution_steps} empty="No steps proposed" />
      </section>

      {/* 6. Test plan */}
      <section className="report-section">
        <div className="label">Test plan</div>
        <List items={report.test_plan} empty="No test plan proposed" />
      </section>

      {/* 8. Warnings / limitations */}
      {report.warnings.length > 0 && (
        <section className="report-section">
          <div className="label">Warnings &amp; limitations</div>
          <ul className="clean">
            {report.warnings.map((w, i) => (
              <li key={i} className="warning">
                ⚠ {w}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
