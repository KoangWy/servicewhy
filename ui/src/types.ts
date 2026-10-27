// Contracts mirror the API (SPEC §6 finding contract, §8 endpoints). The API's /openapi.json is the source.

export interface Evidence {
  evidence_id: string;
  source: string;
  query: string;
  metric: string;
  contrast: string;
  group: string | null;
  value: number | null;
  baseline: number | null;
  n: number;
  n_baseline: number;
  supports: boolean;
}

export interface Finding {
  id: string;
  cause_hypothesis: string;
  evidence: Evidence[];
  confidence: "high" | "medium" | "low";
  effect_size: { metric: string; delta: string; relative: string | null; evidence_id: string };
  uncertainty: string;
  recommended_action: string;
  status: "proposed" | "approved" | "rejected";
  library_id: string;
  family: string;
  run_id?: string;
  approvals?: { timestamp: string; decision: string; role: string }[];
}

export interface RevenueSplit {
  revenue_focus?: number | null;
  revenue_baseline?: number | null;
  change_rel: number | null;
  volume_share: number | null;
  decoy_dominant: boolean;
  evidence_ids: string[];
}

export interface NotCause {
  statement: string;
  negative?: string;
  evidence: { evidence_id: string; value: number | null; baseline: number | null; n: number; unit?: string }[];
}

export interface Insufficient {
  statement: string;
  reasons: string[];
}

export interface RunOutput {
  summary: string;
  answer_type: "answer" | "insufficient_evidence" | "reframed";
  findings: Finding[];
  not_causes: NotCause[];
  insufficient: Insufficient[];
  revenue_split: RevenueSplit | null;
  mode?: { sample_mode?: boolean; data?: string; model?: string; recorded_with?: { data: string; model: string } };
}

export interface RunResponse {
  run_id: string;
  status: "success" | "error";
  question: string;
  output?: RunOutput;
  error?: { type: string; message: string; recoverable: boolean; available_questions?: string[] };
  trace_id?: string;
  log_file?: string;
  execution_time_seconds?: number;
}

export interface Report {
  report_id: string;
  period: { start: string; end: string };
  summary: string;
  findings: Finding[];
  revenue_split: RevenueSplit | null;
  not_causes: NotCause[];
  insufficient: Insufficient[];
  provenance: {
    data: string;
    channel: string;
    model: string;
    data_as_of?: string;
    stores?: Record<string, string[]>;
    comparison?: string;
    runs: { run_id: string; question: string }[];
  };
}

export interface TraceEvent {
  timestamp: string;
  event: string;
  agent_name: string;
  action: string;
  input_summary: string;
  output_summary: string;
  query?: string;
  rows_used?: number;
  verdict?: string;
  retry_count: number;
  status: string;
}

export interface Health {
  status: string;
  zetaris: string;
  model: string;
  sample_mode: boolean;
  sample_questions: string[] | null;
}

/** Body of a structured API error (HTTP 4xx/5xx with status "error"); api.ts passes it through instead of throwing. */
export interface ApiErrorBody {
  status: "error";
  error: { type: string; message: string; recoverable?: boolean; available_questions?: string[] };
  /** Only on 409 ReportInProgress: the generation that is already running. */
  report_job?: { started_at: string; elapsed_s: number } | null;
}

export interface RunSummary {
  run_id: string;
  question: string | null;
  status: "success" | "error";
}

/** Settings API: read-only mode, the model connection (never the token itself) and the provider catalogue. */
export interface ModelSettings {
  provider: "meterless" | "opencode";
  base_url: string;
  model_id: string;
  token_set: boolean;
  source: "env" | "runtime";
}

export interface ProviderInfo {
  id: "meterless" | "opencode";
  label: string;
  primary: boolean;
  default_base_url: string;
  default_model_id: string;
}

export interface Settings {
  mode: { sample_mode: boolean; data_backend: "zetaris" | "local"; model_mode: string };
  model: ModelSettings;
  providers: ProviderInfo[];
}

/** Body of PUT /settings/model and POST /settings/test; every field but the provider is optional. */
export interface ModelSettingsInput {
  provider: string;
  base_url?: string;
  model_id?: string;
  token?: string;
}

export type ConnectionErrorType =
  | "Unreachable" | "Unauthorized" | "NoModels" | "ModelUnavailable" | "ChatFailed" | "Timeout" | "NotConfigured" | "SampleMode";

export interface ConnectionTest {
  ok: boolean;
  provider: string;
  base_url: string;
  latency_ms: number;
  models: string[];
  selected_model: string;
  selected_model_available: boolean;
  routed_model?: string | null;
  note?: string | null;
  error: { type: ConnectionErrorType | string; message: string; hint?: string } | null;
}

/** GET /activity: what the API is doing right now. Everything is in-memory on the server and bounded. */
export type RunKind = "ask" | "report" | "drilldown";
export type Stage = "Planner" | "Investigator" | "Verifier" | "Writer";

export interface ActivityEvent {
  event: string;
  agent: string;
  action: string;
  summary: string;
  status: string;
  at: string;
}

export interface ActiveRun {
  run_id: string;
  kind: RunKind;
  question: string;
  started_at: string;
  elapsed_s: number;
  stage: Stage | null;
  counts: { events: number; queries: number; model_calls: number; blocks: number; retries: number };
  model: string | null;
  recent_events: ActivityEvent[];
}

export interface FinishedRun {
  run_id: string;
  kind: string;
  question: string;
  status: "success" | "error";
  elapsed_s: number;
  finished_at: string;
}

export interface ReportJob {
  started_at: string;
  elapsed_s: number;
}

export interface Activity {
  now: string;
  active: ActiveRun[];
  recent: FinishedRun[];
  report_job: ReportJob | null;
}
