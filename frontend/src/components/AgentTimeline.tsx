"use client";

import type { ExecutionEvent } from "@/lib/types";

interface AgentTimelineProps {
  events: ExecutionEvent[];
  status: string;
}

interface Rendered {
  marker: string;
  cls: string;
  tool: string | null;
  msg: string;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function render(event: ExecutionEvent): Rendered {
  const tool = event.tool_name;
  switch (event.event_type) {
    case "tool_started":
      return { marker: "▸", cls: "started", tool, msg: "started" };
    case "tool_completed":
      return { marker: "✓", cls: "completed", tool, msg: event.summary };
    case "tool_failed":
      return {
        marker: "✕",
        cls: "failed",
        tool,
        msg: event.summary || "tool failed",
      };
    case "approval_proposed":
      return { marker: "✎", cls: "pending", tool, msg: event.summary };
    case "write_executed":
      return {
        marker: "✓",
        cls: "completed",
        tool,
        msg: event.summary || "write executed",
      };
    case "approval_resolved":
      return { marker: "●", cls: "pending", tool, msg: event.summary };
    case "report_generated":
      return { marker: "▣", cls: "completed", tool: null, msg: event.summary };
    case "limit_reached":
      return { marker: "⛔", cls: "failed", tool: null, msg: event.summary };
    case "analysis_failed":
      return { marker: "✕", cls: "failed", tool: null, msg: event.summary };
    case "analysis_completed":
      return { marker: "✔", cls: "completed", tool: null, msg: event.summary };
    case "analysis_started":
      return { marker: "●", cls: "started", tool: null, msg: event.summary };
    default:
      return { marker: "•", cls: "info", tool: null, msg: event.summary };
  }
}

export default function AgentTimeline({ events, status }: AgentTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="empty-hint">
        {status === "queued" || status === "running"
          ? "Agent is starting…"
          : "No execution events yet. Start an analysis to watch the agent work."}
      </div>
    );
  }
  return (
    <ul className="timeline">
      {events.map((event) => {
        const r = render(event);
        return (
          <li key={event.sequence} className={r.cls}>
            <span className="marker">{r.marker}</span>
            {r.tool && <span className="tool">{r.tool}</span>}
            <span className="msg">{r.msg}</span>
            <span className="time">{formatTime(event.created_at)}</span>
          </li>
        );
      })}
    </ul>
  );
}
