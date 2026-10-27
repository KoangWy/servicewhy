import type { RunResponse } from "../types";
import { Badge, FindingCard, Outcomes, SplitBar, Summary } from "./common";
import { VerifierNote } from "./VerifierNote";

const TYPE_LABEL: Record<string, string> = { answer: "Answer", insufficient_evidence: "Insufficient evidence", reframed: "Reframed question" };

export function Answer({ run, onAsk }: { run: RunResponse; onAsk?: (q: string) => void }) {
  if (run.status === "error" || !run.output) {
    const err = run.error;
    return (
      <div role="alert" className="rounded-card border border-bad-line bg-bad-bg p-4 text-sm">
        <p className="text-bad-fg">
          <strong className="font-semibold">{err?.type}:</strong> {err?.message}
        </p>
        {err?.available_questions ? (
          <div className="mt-3">
            <p className="text-muted">Recorded questions you can ask:</p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {err.available_questions.map((q) => (
                <li key={q}>
                  {onAsk ? (
                    <button type="button" onClick={() => onAsk(q)} className="rounded-control border border-line bg-surface px-3 py-2 text-left text-ink transition-colors duration-150 hover:bg-surface-2">
                      {q}
                    </button>
                  ) : (
                    <span className="text-ink">{q}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    );
  }
  const o = run.output;
  const rec = o.mode?.recorded_with;
  const note = o.mode?.sample_mode
    ? `Recorded replay${rec ? ` of a run made with ${rec.data} and ${rec.model}` : ""}. No services were called for this answer.`
    : o.mode?.data ? `Data: ${o.mode.data} · Model: ${o.mode.model}` : null;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Badge tone={o.answer_type === "answer" ? "accent" : "neutral"}>{TYPE_LABEL[o.answer_type] ?? o.answer_type.replace("_", " ")}</Badge>
        <span className="font-mono text-xs text-muted">{run.run_id}</span>
        <a href={`#/trace/${run.run_id}`} className="ml-auto text-sm font-medium text-accent-ink underline-offset-4 hover:underline">
          Evidence &amp; trace →
        </a>
      </div>
      <VerifierNote runId={run.run_id} />
      <Summary text={o.summary} />
      {o.revenue_split ? <SplitBar split={o.revenue_split} /> : null}
      {o.findings.length ? (
        <div className="grid gap-3">
          {o.findings.map((f) => <FindingCard key={f.id} f={f} />)}
        </div>
      ) : null}
      <Outcomes notCauses={o.not_causes} insufficient={o.insufficient} />
      {note ? <p className="text-xs text-muted">{note}</p> : null}
    </div>
  );
}
