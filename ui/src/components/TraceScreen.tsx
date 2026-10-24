import { useEffect, useState } from "react";
import { api } from "../api";
import type { TraceEvent } from "../types";

export function TraceScreen({ runId, go }: { runId: string; go: (p: string) => void }) {
  const [events, setEvents] = useState<TraceEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWm, setShowWm] = useState(false);

  useEffect(() => {
    api.trace(runId).then((t) => setEvents(t.events)).catch((e) => setError(String(e)));
  }, [runId]);

  if (error) return <div className="panel answer error">{error}</div>;
  if (!events) return <div className="panel muted">Loading trace…</div>;

  const shown = events.filter((e) => showWm || e.event !== "wm_mutation");
  const count = (k: string) => events.filter((e) => e.event === k).length;
  return (
    <section className="panel">
      <button className="link" onClick={() => go("/")}>← Report</button>
      <h2>Evidence &amp; trace · {runId}</h2>
      <div className="stats">
        <span>{count("query")} federated queries</span>
        <span>{count("evidence")} evidence items</span>
        <span>{count("verify")} verifier checks</span>
        <span className="warn">{events.filter((e) => e.verdict === "block").length} blocks</span>
        <span>{count("retry")} retries</span>
        <span>{count("wm_mutation")} world-model writes</span>
        <label><input type="checkbox" checked={showWm} onChange={(e) => setShowWm(e.target.checked)} /> show world-model writes</label>
      </div>
      <ol className="timeline">
        {shown.map((e, i) => (
          <li key={i} className={`ev ev-${e.event} role-${e.agent_name.toLowerCase()}`}>
            <div className="ev-head">
              <span className="role">{e.agent_name}</span>
              <span className="action">{e.action}</span>
              {e.verdict ? <span className={`badge verdict-${e.verdict}`}>{e.verdict}</span> : null}
              {e.retry_count ? <span className="badge retry">retry {e.retry_count}</span> : null}
              {e.rows_used != null ? <span className="muted">{e.rows_used} rows</span> : null}
            </div>
            <div className="ev-body">{e.output_summary || e.input_summary}</div>
            {e.query ? <details><summary>query</summary><pre>{e.query}</pre></details> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
