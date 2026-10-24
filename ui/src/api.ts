import type { Finding, Health, Report, RunResponse, TraceEvent } from "./types";

const BASE = "/api";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok && !(body && body.status === "error")) {
    throw new Error(body?.detail || `${res.status} ${res.statusText}`);
  }
  return body as T;
}

const post = <T,>(path: string, body: unknown = {}) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => call<Health>("/health"),
  run: (query: string, context?: string) => post<RunResponse>("/run", { input: { query, context } }),
  listReports: () => call<{ report_id: string }[]>("/reports"),
  createReport: () => post<{ report_id: string }>("/reports", {}),
  report: (id: string) => call<Report>(`/reports/${id}`),
  finding: (id: string) => call<Finding>(`/findings/${id}`),
  decide: (id: string, decision: "approve" | "reject") => post<Finding>(`/findings/${id}/${decision}`, { role: "manager" }),
  drilldown: (id: string, question?: string) =>
    post<{ parent_finding: string; run: RunResponse }>(`/findings/${id}/drilldown`, { question: question || null }),
  trace: (runId: string) => call<{ run_id: string; events: TraceEvent[] }>(`/traces/${runId}`),
};
