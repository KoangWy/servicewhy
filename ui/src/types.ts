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
}
