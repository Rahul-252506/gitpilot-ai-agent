"use client";

import type { AnalysisListItem } from "@/lib/types";

interface HistoryListProps {
  items: AnalysisListItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
}

function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function HistoryList({
  items,
  activeId,
  onSelect,
}: HistoryListProps) {
  if (items.length === 0) {
    return <div className="meta">No analyses yet.</div>;
  }
  return (
    <ul className="history-list">
      {items.map((item) => (
        <li key={item.analysis_id} style={{ listStyle: "none" }}>
          <button
            className="history-item"
            onClick={() => onSelect(item.analysis_id)}
            disabled={item.analysis_id === activeId}
            title={shortTime(item.created_at)}
          >
            <span className="repo">
              {item.repository}
              <span className="num"> #{item.issue_number}</span>
            </span>
            <span className={`st ${item.status}`}>{item.status}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
