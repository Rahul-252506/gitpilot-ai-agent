// Types mirroring the backend API schemas (backend/app/schemas/api.py).
// Keep in sync with the FastAPI Pydantic response models.

export type AnalysisStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed";

export type ApprovalStatus = "pending" | "approved" | "rejected" | "failed";

export type WriteActionType = "add_issue_label" | "add_issue_comment";

export interface ExecutionEvent {
  sequence: number;
  event_type: string;
  tool_name: string | null;
  status: string;
  summary: string;
  created_at: string;
}

export interface EvidenceItem {
  source: string;
  quote: string;
  kind: "confirmed" | "hypothesis";
}

export interface ProposedAction {
  action_type: WriteActionType;
  payload: Record<string, unknown>;
  rationale: string;
}

export interface ResolutionReport {
  issue_summary: string;
  category: string;
  priority: string;
  root_cause: string;
  evidence: EvidenceItem[];
  affected_files: string[];
  resolution_steps: string[];
  test_plan: string[];
  confidence: number;
  warnings: string[];
  proposed_actions: ProposedAction[];
}

export interface Approval {
  id: string;
  action_type: WriteActionType;
  payload: Record<string, unknown>;
  rationale: string;
  status: ApprovalStatus;
  created_at: string;
  resolved_at: string | null;
  error_message: string | null;
}

export interface AnalysisDetail {
  analysis_id: string;
  repository: string;
  issue_number: number;
  status: AnalysisStatus;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  events: ExecutionEvent[];
  report: ResolutionReport | null;
  approvals: Approval[];
}

export interface AnalysisListItem {
  analysis_id: string;
  repository: string;
  issue_number: number;
  status: AnalysisStatus;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface AnalysisList {
  items: AnalysisListItem[];
  total: number;
}

export interface HealthInfo {
  status: string;
  /** "demo" when the backend runs the clearly-labeled demo fixture. */
  mode: "live" | "demo";
}

export interface ApiErrorBody {
  detail?: { code?: string; message?: string };
}

export interface ApprovalDecision {
  analysis_id: string;
  approval_id: string;
  status: string;
  error_message: string | null;
}
