import type {
  AnalysisDetail,
  AnalysisList,
  ApprovalDecision,
  ApiErrorBody,
  HealthInfo,
} from "./types";

export const API_BASE_URL: string =
  (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined)?.replace(
    /\/$/,
    ""
  ) || "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError(
      `Cannot reach the GitPilot backend at ${API_BASE_URL}. Is it running?`,
      "network_error",
      0
    );
  }

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    const err = (body ?? {}) as ApiErrorBody;
    const message =
      err.detail?.message || `Request failed with status ${response.status}`;
    const code = err.detail?.code || "request_failed";
    throw new ApiError(message, code, response.status);
  }
  return body as T;
}

export interface StartAnalysisResult {
  analysis_id: string;
  status: string;
}

export function startAnalysis(
  repository: string,
  issueNumber: number
): Promise<StartAnalysisResult> {
  return request<StartAnalysisResult>("/api/analyses", {
    method: "POST",
    body: JSON.stringify({ repository, issue_number: issueNumber }),
  });
}

export function getAnalysis(analysisId: string): Promise<AnalysisDetail> {
  return request<AnalysisDetail>(`/api/analyses/${analysisId}`);
}

export function listAnalyses(limit = 10): Promise<AnalysisList> {
  return request<AnalysisList>(`/api/analyses?limit=${limit}`);
}

export function approve(
  analysisId: string,
  approvalId?: string
): Promise<ApprovalDecision> {
  return request<ApprovalDecision>(`/api/analyses/${analysisId}/approve`, {
    method: "POST",
    body: JSON.stringify(approvalId ? { approval_id: approvalId } : {}),
  });
}

export function reject(
  analysisId: string,
  approvalId?: string
): Promise<ApprovalDecision> {
  return request<ApprovalDecision>(`/api/analyses/${analysisId}/reject`, {
    method: "POST",
    body: JSON.stringify(approvalId ? { approval_id: approvalId } : {}),
  });
}

export function health(): Promise<HealthInfo> {
  return request<HealthInfo>("/api/health");
}

export function isActive(status: string): boolean {
  return ["queued", "running", "waiting_approval"].includes(status);
}
