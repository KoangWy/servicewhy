import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { ApiErrorBody, Finding, Health, RunResponse } from "../types";
import { Answer } from "./Answer";
import { Badge, btnPrimary, btnSecondary, Confidence, field, fmtMetric, linkAction, metricLabel, panel, Status } from "./common";
import { VerifierNote } from "./VerifierNote";

const isApiError = (b: unknown): b is ApiErrorBody => (b as ApiErrorBody | undefined)?.status === "error";

function Alert({ children }: { children: ReactNode }) {
  return <div role="alert" className="rounded-card border border-bad-line bg-bad-bg p-4 text-sm text-bad-fg">{children}</div>;
}

export function FindingScreen({ id, health }: { id: string; health: Health | null }) {
  const [f, setF] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<"approve" | "reject" | null>(null);
  const [decideError, setDecideError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [drill, setDrill] = useState<RunResponse | null>(null);
  const [drillError, setDrillError] = useState<{ type?: string; message: string } | null>(null);

  useEffect(() => {
    setF(null);
    setError(null);
    api.finding(id).then(setF).catch((e) => setError(String(e)));
  }, [id]);

  if (error) {
    return <div className="space-y-4"><a href="#/" className={linkAction}>← Report</a><Alert>{error}</Alert></div>;
  }
  if (!f) return <p role="status" className="text-sm text-muted">Loading finding…</p>;

  const sample = !!health?.sample_mode;
  const last = f.approvals?.length ? f.approvals[f.approvals.length - 1] : null;

  const decide = async (d: "approve" | "reject") => {
    setDeciding(d);
    setDecideError(null);
    try {
      const body: unknown = await api.decide(f.id, d);
      if (isApiError(body)) throw new Error(`${body.error.type}: ${body.error.message}`);
      const updated = body as Finding;
      // The decision response has no run_id; keep the one this screen already has so the trace link stays.
      setF({ ...updated, run_id: updated.run_id ?? f.run_id });
    } catch (e) {
      setDecideError(`Could not ${d} this finding: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeciding(null);
    }
  };

  const drilldown = async () => {
    setBusy(true);
    setDrill(null);
    setDrillError(null);
    try {
      const res: unknown = await api.drilldown(f.id, q.trim() || undefined);
      if (isApiError(res)) setDrillError({ type: res.error.type, message: res.error.message });
      else if ((res as { run?: RunResponse } | undefined)?.run) setDrill((res as { run: RunResponse }).run);
      else setDrillError({ message: "The API returned no run for this drill-down." });
    } catch (e) {
      setDrillError({ message: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <a href="#/" className={linkAction}>← Report</a>
        {f.run_id ? <a href={`#/trace/${f.run_id}`} className={linkAction}>Full evidence &amp; trace for this run →</a> : null}
      </div>

      <header className="space-y-4">
        <div className="flex flex-wrap items-center gap-2"><Confidence level={f.confidence} /><Status status={f.status} /></div>
        <h2 className="max-w-3xl text-balance text-2xl/8 font-semibold text-ink sm:text-3xl/10">{f.cause_hypothesis}</h2>
      </header>

      {f.run_id ? <VerifierNote runId={f.run_id} /> : null}

      <section className={panel} aria-label="Effect and action">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="text-4xl font-semibold tabular-nums text-ink">{f.effect_size.delta}</span>
          <span className="text-base tabular-nums text-muted">
            {f.effect_size.relative ? `${f.effect_size.relative} · ` : ""}{metricLabel(f.effect_size.metric)}
          </span>
          <span className="rounded border border-line bg-surface-2 px-1 font-mono text-[11px] text-muted" title="evidence id">{f.effect_size.evidence_id}</span>
        </div>
        <dl className="mt-6 grid gap-x-8 gap-y-4 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]">
          <dt className="text-muted">Uncertainty</dt>
          <dd className="text-ink">{f.uncertainty}</dd>
          <dt className="text-muted">Recommended action</dt>
          <dd className="font-medium text-ink">{f.recommended_action}</dd>
        </dl>
        <div className="mt-6 border-t border-line pt-5">
          <p className="text-sm text-muted">The manager approves every action before it counts as accepted.</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button className={btnPrimary} disabled={f.status !== "proposed" || deciding !== null} onClick={() => decide("approve")}>
              {deciding === "approve" ? "Approving…" : "Approve"}
            </button>
            <button className={btnSecondary} disabled={f.status !== "proposed" || deciding !== null} onClick={() => decide("reject")}>
              {deciding === "reject" ? "Rejecting…" : "Reject"}
            </button>
            {last ? <span className="text-sm text-muted">{last.decision} by {last.role} at <span className="tabular-nums">{last.timestamp}</span></span> : null}
          </div>
          {decideError ? <div className="mt-3"><Alert>{decideError}</Alert></div> : null}
        </div>
      </section>

      <section className={panel} aria-labelledby="evidence-h">
        <h3 id="evidence-h" className="text-base font-semibold text-ink">Evidence</h3>
        <div className="mt-4 overflow-x-auto rounded-control border border-line">
          <table className="w-full min-w-[46rem] border-collapse text-left text-sm tabular-nums">
            <thead className="bg-surface-2 text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Evidence</th>
                <th className="px-3 py-2 font-medium">Metric</th>
                <th className="px-3 py-2 font-medium">Group</th>
                <th className="px-3 py-2 text-right font-medium">Value</th>
                <th className="px-3 py-2 text-right font-medium">Baseline</th>
                <th className="px-3 py-2 font-medium">n</th>
                <th className="px-3 py-2 font-medium">Contrast</th>
                <th className="px-3 py-2 font-medium">Supports</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {f.evidence.map((e) => (
                <tr key={e.evidence_id} className="align-top">
                  <td className="px-3 py-3">
                    <span className="rounded border border-line bg-surface-2 px-1 font-mono text-[11px] text-muted">{e.evidence_id}</span>
                    <details className="mt-1.5">
                      <summary className="cursor-pointer text-xs font-medium text-accent-ink">SQL</summary>
                      <pre className="mt-2 max-h-64 w-80 overflow-auto whitespace-pre-wrap break-words rounded-control bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-ink">{e.query}</pre>
                      <div className="mt-1 max-w-80 text-xs text-muted">{e.source}</div>
                    </details>
                  </td>
                  <td className="px-3 py-3 text-ink">{metricLabel(e.metric)}</td>
                  <td className="px-3 py-3 text-ink">{e.group ?? "-"}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-medium text-ink">{fmtMetric(e.metric, e.value)}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right text-muted">{fmtMetric(e.metric, e.baseline)}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-muted">{e.n} vs {e.n_baseline}</td>
                  <td className="px-3 py-3 text-xs text-muted">{e.contrast}</td>
                  <td className="px-3 py-3"><Badge tone={e.supports ? "ok" : "neutral"}>{e.supports ? "yes" : "no"}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={panel} aria-labelledby="drill-h">
        <h3 id="drill-h" className="text-base font-semibold text-ink">Drill down</h3>
        <p className="mt-1 text-sm text-muted">
          {sample
            ? "SAMPLE mode replays recorded runs: only findings with a recorded drill-down can be expanded, and the question field is not used."
            : "Re-run the investigation for this one finding with fresh queries."}
        </p>
        <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); drilldown(); }}>
          <input className={field} aria-label="drill-down question" value={q} disabled={sample} placeholder={`Why: ${f.cause_hypothesis}?`} onChange={(e) => setQ(e.target.value)} />
          <button className={`${btnPrimary} sm:w-28`} disabled={busy} aria-busy={busy}>{busy ? "Investigating…" : "Ask why"}</button>
        </form>
        <div aria-live="polite" className="mt-4 empty:hidden">
          {busy ? <p role="status" className="text-sm text-muted">Investigating this finding…</p> : null}
          {drillError ? (
            <div role="alert" className={`rounded-card border p-4 text-sm ${drillError.type === "SampleModeMiss" ? "border-warn-line bg-warn-bg" : "border-bad-line bg-bad-bg"}`}>
              {drillError.type === "SampleModeMiss" ? (
                <p className="font-medium text-warn-fg">Drill-down needs the live stack; SAMPLE mode replays recorded runs. This finding has no recorded drill-down.</p>
              ) : (
                <p className="font-medium text-bad-fg">The drill-down failed.</p>
              )}
              <p className="mt-1 text-muted">{drillError.type ? `${drillError.type}: ` : ""}{drillError.message}</p>
            </div>
          ) : null}
          {drill ? <div className="border-t border-line pt-6"><Answer run={drill} /></div> : null}
        </div>
      </section>
    </div>
  );
}
