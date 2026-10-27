import type { Activity, ApiErrorBody, ConnectionTest, Finding, Health, ModelSettingsInput, Report, RunResponse, RunSummary, Settings, TraceEvent } from "./types";

const BASE = "/api";

/** A non-2xx answer that is not a structured error body; the status lets callers tell "no such endpoint" from a failure. */
export class HttpError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok && !(body && body.status === "error")) {
    throw new HttpError(body?.detail || `${res.status} ${res.statusText}`, res.status);
  }
  return body as T;
}

const post = <T,>(path: string, body: unknown = {}) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

const put = <T,>(path: string, body: unknown = {}) => call<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const isApiError = (body: unknown): body is ApiErrorBody => (body as ApiErrorBody | undefined)?.status === "error";

export const api = {
  health: () => call<Health>("/health"),
  run: (query: string, context?: string, runId?: string) =>
    post<RunResponse>("/run", { input: { query, context }, ...(runId ? { run_id: runId } : {}) }),
  listReports: () => call<{ report_id: string }[]>("/reports"),
  createReport: () => post<{ report_id: string } | ApiErrorBody>("/reports", {}),
  report: (id: string) => call<Report>(`/reports/${id}`),
  finding: (id: string) => call<Finding>(`/findings/${id}`),
  decide: (id: string, decision: "approve" | "reject") => post<Finding>(`/findings/${id}/${decision}`, { role: "manager" }),
  drilldown: (id: string, question?: string) =>
    post<{ parent_finding: string; run: RunResponse }>(`/findings/${id}/drilldown`, { question: question || null }),
  runs: () => call<RunSummary[]>("/runs"),
  settings: () => call<Settings>("/settings"),
  saveModel: (input: ModelSettingsInput) => put<Settings | ApiErrorBody>("/settings/model", input),
  testModel: (input: ModelSettingsInput) => post<ConnectionTest>("/settings/test", input),
  activity: () => call<Activity>("/activity"),
  trace: (runId: string) => call<{ run_id: string; events: TraceEvent[] }>(`/traces/${runId}`),
};
