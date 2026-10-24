import { useEffect, useState } from "react";
import { api } from "../api";
import type { Finding, RunResponse } from "../types";
import { Answer } from "./Answer";
import { Confidence, Status } from "./common";

function num(v: number | null): string {
  if (v == null) return "n/a";
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
}

export function FindingScreen({ id, go }: { id: string; go: (p: string) => void }) {
  const [f, setF] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [drill, setDrill] = useState<RunResponse | null>(null);

  useEffect(() => {
    api.finding(id).then(setF).catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <div className="panel answer error">{error}</div>;
  if (!f) return <div className="panel muted">Loading finding…</div>;

  const decide = async (d: "approve" | "reject") => setF(await api.decide(f.id, d));
  const drilldown = async () => {
    setBusy(true);
    try {
      setDrill((await api.drilldown(f.id, q.trim() || undefined)).run);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <section className="panel">
        <button className="link" onClick={() => go("/")}>← Report</button>
        <h2 className="cause-big">{f.cause_hypothesis}</h2>
        <div className="card-top"><Confidence level={f.confidence} /><Status status={f.status} /></div>
        <dl className="facts">
          <dt>Effect</dt>
          <dd>{f.effect_size.metric.replace(/_/g, " ")}: <b>{f.effect_size.delta}</b> {f.effect_size.relative ? `(${f.effect_size.relative})` : ""} <span className="cite">{f.effect_size.evidence_id}</span></dd>
          <dt>Uncertainty</dt>
          <dd>{f.uncertainty}</dd>
          <dt>Recommended action</dt>
          <dd>{f.recommended_action}</dd>
        </dl>
        <div className="approve">
          <span className="muted">The manager approves every action before it counts as accepted.</span>
          <button className="ok" disabled={f.status !== "proposed"} onClick={() => decide("approve")}>Approve</button>
          <button className="no" disabled={f.status !== "proposed"} onClick={() => decide("reject")}>Reject</button>
          {f.approvals?.length ? <span className="muted"> {f.approvals[f.approvals.length - 1].decision} by {f.approvals[f.approvals.length - 1].role} at {f.approvals[f.approvals.length - 1].timestamp}</span> : null}
        </div>
      </section>

      <section className="panel">
        <h3>Evidence</h3>
        <table className="evidence">
          <thead>
            <tr><th>Evidence</th><th>Metric</th><th>Group</th><th>Value</th><th>Baseline</th><th>n</th><th>Contrast</th><th>Supports</th></tr>
          </thead>
          <tbody>
            {f.evidence.map((e) => (
              <tr key={e.evidence_id}>
                <td>
                  <span className="cite">{e.evidence_id}</span>
                  <details><summary>SQL</summary><pre>{e.query}</pre><div className="muted">{e.source}</div></details>
                </td>
                <td>{e.metric.replace(/_/g, " ")}</td>
                <td>{e.group ?? "-"}</td>
                <td>{num(e.value)}</td>
                <td>{num(e.baseline)}</td>
                <td>{e.n} vs {e.n_baseline}</td>
                <td className="small">{e.contrast}</td>
                <td>{e.supports ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {f.run_id ? <button className="link" onClick={() => go(`/trace/${f.run_id}`)}>Full evidence &amp; trace for this run →</button> : null}
      </section>

      <section className="panel">
        <h3>Drill down</h3>
        <form className="ask" onSubmit={(e) => { e.preventDefault(); drilldown(); }}>
          <input aria-label="drill-down question" value={q} placeholder={`Why: ${f.cause_hypothesis}?`} onChange={(e) => setQ(e.target.value)} />
          <button disabled={busy}>{busy ? "Investigating…" : "Ask why"}</button>
        </form>
        {drill ? <Answer run={drill} go={go} /> : null}
      </section>
    </div>
  );
}
