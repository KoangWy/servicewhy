import { useEffect, useState } from "react";
import { api } from "../api";
import type { Health, TraceEvent } from "../types";
import { Badge, linkAction, panel } from "./common";

const EVENT_STYLE: Record<string, string> = {
  block: "border-l-bad-fg bg-bad-bg/60",
  retry: "border-l-warn-fg bg-warn-bg/60",
  answer: "border-l-ok-fg",
};

function Stat({ label, value, alert }: { label: string; value: number; alert?: boolean }) {
  return (
    <div className="rounded-control border border-line bg-surface px-3 py-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`text-xl font-semibold tabular-nums ${alert && value > 0 ? "text-bad-fg" : "text-ink"}`}>{value}</dd>
    </div>
  );
}

export function TraceScreen({ runId, health }: { runId: string; health: Health | null }) {
  const [events, setEvents] = useState<TraceEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWm, setShowWm] = useState(false);

  useEffect(() => {
    setEvents(null);
    setError(null);
    api.trace(runId).then((t) => setEvents(t.events)).catch((e) => setError(String(e)));
  }, [runId]);

  if (error) {
    return (
      <div className="space-y-4">
        <a href="#/" className={linkAction}>← Report</a>
        <div role="alert" className="rounded-card border border-bad-line bg-bad-bg p-4 text-sm text-bad-fg">{error}</div>
      </div>
    );
  }
  if (!events) return <p role="status" className="text-sm text-muted">Loading trace…</p>;

  const shown = events.filter((e) => showWm || e.event !== "wm_mutation");
  const count = (k: string) => events.filter((e) => e.event === k).length;
  const reQueries = events.filter((e) => e.event === "query" && e.agent_name === "Verifier").length;
  return (
    <div className="space-y-6">
      <a href="#/" className={linkAction}>← Report</a>
      <header>
        <h2 className="text-2xl font-semibold text-ink">Evidence &amp; trace</h2>
        <p className="mt-1 font-mono text-sm text-muted">{runId}</p>
      </header>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Federated queries" value={count("query")} />
        <Stat label="Evidence items" value={count("evidence")} />
        <Stat label="Verifier checks" value={count("verify")} />
        <Stat label="Blocks" value={events.filter((e) => e.verdict === "block").length} alert />
        <Stat label="Retries" value={count("retry")} />
        <Stat label="World-model writes" value={count("wm_mutation")} />
      </dl>

      <section className="rounded-card border border-line bg-surface-2/60 p-4 text-sm text-muted" aria-label="Run provenance">
        <p>
          <strong className="font-semibold text-ink">Zetaris:</strong> {count("query")} federated SQL queries in this run, {reQueries} of them the verifier's independent re-queries.{" "}
          <strong className="font-semibold text-ink">Meterless:</strong> {count("wm_mutation")} world-model writes, each recorded with its provenance.
        </p>
        <p className="mt-2">
          {health?.sample_mode
            ? "Recorded replay: this trace was captured when the run was recorded. Nothing was queried or written just now."
            : "These counts come from this run's trace log."}
        </p>
      </section>

      <section className={panel} aria-labelledby="timeline-h">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="timeline-h" className="text-base font-semibold text-ink">Timeline</h3>
          <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-sm text-muted">
            <input type="checkbox" className="size-4 accent-accent" checked={showWm} onChange={(e) => setShowWm(e.target.checked)} />
            show world-model writes
          </label>
        </div>
        <ol className="mt-4 space-y-2">
          {shown.map((e, i) => (
            <li key={i} className={`rounded-r-control border-l-2 py-2 pl-4 pr-3 ${EVENT_STYLE[e.event] ?? "border-l-line-strong"}`}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className="font-semibold text-ink">{e.agent_name}</span>
                <span className="font-mono text-xs text-muted">{e.action}</span>
                {e.verdict ? <Badge tone={e.verdict === "block" ? "bad" : e.verdict === "pass" ? "ok" : "warn"}>{e.verdict}</Badge> : null}
                {e.retry_count ? <Badge tone="warn">retry {e.retry_count}</Badge> : null}
                {e.rows_used != null ? <span className="text-xs tabular-nums text-muted">{e.rows_used} rows</span> : null}
              </div>
              <div className="mt-1 break-words text-sm text-muted">{e.output_summary || e.input_summary}</div>
              {e.query ? (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs font-medium text-accent-ink">query</summary>
                  <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-control bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-ink">{e.query}</pre>
                </details>
              ) : null}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
