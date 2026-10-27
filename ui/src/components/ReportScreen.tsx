import { useEffect, useState } from "react";
import { api } from "../api";
import type { Health, Report, RunResponse } from "../types";
import { Answer } from "./Answer";
import { btnPrimary, field, fmt, FindingCard, Outcomes, panel, SplitBar, Summary } from "./common";
import { VerifierNote } from "./VerifierNote";

const SUGGESTED = [
  "Why did Saturday dinner revenue drop 18%?",
  "Is the kitchen slow on Saturdays?",
  "Why do tables reset so slowly late evening?",
  "Who is our worst server?",
];
const VISIBLE_SUGGESTIONS = 4;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return m ? `${d} ${MONTHS[m - 1]} ${y}` : iso;
};

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums text-ink">{value}</dd>
      {sub ? <dd className="mt-0.5 text-sm tabular-nums text-muted">{sub}</dd> : null}
    </div>
  );
}

function Provenance({ report, replay }: { report: Report; replay: boolean }) {
  const p = report.provenance;
  return (
    <section className={panel} aria-labelledby="prov-h">
      <h3 id="prov-h" className="text-base font-semibold text-ink">Data provenance</h3>
      <p className="mt-1 text-sm text-muted">{p.data}</p>
      {replay ? <p className="mt-1 text-sm text-muted">This describes the run that was recorded; nothing was queried just now.</p> : null}
      <dl className="mt-4 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-[auto_minmax(0,1fr)]">
        <dt className="text-muted">Channel</dt>
        <dd className="text-ink">{p.channel}</dd>
        <dt className="text-muted">Model</dt>
        <dd className="text-ink">{p.model}</dd>
        {p.data_as_of ? <><dt className="text-muted">Data as of</dt><dd className="tabular-nums text-ink">{p.data_as_of}</dd></> : null}
        {p.stores ? (
          <>
            <dt className="text-muted">Stores</dt>
            <dd className="space-y-1 text-ink">
              {Object.entries(p.stores).map(([store, tables]) => (
                <div key={store}>{store}: <span className="font-mono text-xs text-muted">{tables.join(", ")}</span></div>
              ))}
            </dd>
          </>
        ) : null}
        {p.comparison ? <><dt className="text-muted">Comparison</dt><dd className="text-ink">{p.comparison}</dd></> : null}
        {p.runs.length ? (
          <>
            <dt className="text-muted">Runs</dt>
            <dd className="space-y-1">
              {p.runs.map((r) => (
                <div key={r.run_id}>
                  <a href={`#/trace/${r.run_id}`} className="font-mono text-xs text-accent-ink underline-offset-4 hover:underline">{r.run_id}</a>
                  <span className="text-ink">: {r.question}</span>
                </div>
              ))}
            </dd>
          </>
        ) : null}
      </dl>
    </section>
  );
}

export function ReportScreen({ health }: { health: Health | null }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RunResponse | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const list = await api.listReports();
        const id = list.length ? list[list.length - 1].report_id : (await api.createReport()).report_id;
        setReport(await api.report(id));
      } catch (e) {
        setError(String(e));
      }
    })();
  }, []);

  const ask = async (q: string) => {
    setQuestion(q);
    setBusy(true);
    setRun(null);
    try {
      setRun(await api.run(q));
    } catch (e) {
      setRun({ run_id: "", status: "error", question: q, error: { type: "RequestFailed", message: String(e), recoverable: true } });
    } finally {
      setBusy(false);
    }
  };

  const suggestions = health?.sample_questions?.slice(0, 10) || SUGGESTED;
  const shown = showAll ? suggestions : suggestions.slice(0, VISIBLE_SUGGESTIONS);
  const rs = report?.revenue_split;
  const byLevel = (l: string) => report?.findings.filter((f) => f.confidence === l).length ?? 0;
  return (
    <div className="space-y-12">
      <section className={panel} aria-labelledby="ask-h">
        <h2 id="ask-h" className="text-lg font-semibold text-ink">Ask why</h2>
        <p className="mt-1 text-sm text-muted">Ask about a change in revenue or service. The verifier blocks any claim the data does not support.</p>
        <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask(question.trim()); }}>
          <input className={field} aria-label="question" value={question} placeholder="Why did Saturday dinner revenue drop 18%?" onChange={(e) => setQuestion(e.target.value)} />
          <button className={`${btnPrimary} sm:w-28`} disabled={busy || !question.trim()}>{busy ? "Investigating…" : "Ask"}</button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {shown.map((q) => (
            <button key={q} type="button" onClick={() => ask(q)} disabled={busy}
                    className="rounded-full border border-line bg-surface-2 px-3 py-1.5 text-left text-sm text-ink transition-colors duration-150 hover:border-line-strong disabled:opacity-50">
              {q}
            </button>
          ))}
          {suggestions.length > VISIBLE_SUGGESTIONS ? (
            <button type="button" aria-expanded={showAll} onClick={() => setShowAll(!showAll)} className="rounded-full px-3 py-1.5 text-sm font-medium text-accent-ink hover:underline">
              {showAll ? "Show fewer" : `Show ${suggestions.length - VISIBLE_SUGGESTIONS} more`}
            </button>
          ) : null}
        </div>
        <div aria-live="polite">
          {busy ? <p role="status" className="mt-6 text-sm text-muted">Investigating: planning, querying, then verifying every number…</p> : null}
          {run ? <div className="mt-6 border-t border-line pt-6"><Answer run={run} onAsk={ask} /></div> : null}
        </div>
      </section>

      <section aria-labelledby="report-h" className="space-y-8">
        <div>
          <h2 id="report-h" className="text-lg font-semibold text-ink">Weekly report</h2>
          {report ? (
            <p className="mt-0.5 text-sm tabular-nums text-muted">
              {day(report.period.start)} to {day(report.period.end)}
              {report.provenance.data_as_of ? ` · data as of ${report.provenance.data_as_of}` : ""}
            </p>
          ) : null}
        </div>
        {error ? <div role="alert" className="rounded-card border border-bad-line bg-bad-bg p-4 text-sm text-bad-fg">{error}</div> : null}
        {!report && !error ? <p role="status" className="text-sm text-muted">Generating the report (a batch run of the same agent)…</p> : null}
        {report ? (
          <>
            <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {rs?.revenue_focus != null ? (
                <Stat label="Revenue"
                      value={fmt(rs.revenue_focus, "usd")}
                      sub={rs.change_rel != null && rs.revenue_baseline != null
                        ? `${rs.change_rel > 0 ? "+" : ""}${(rs.change_rel * 100).toFixed(1)}% vs ${fmt(rs.revenue_baseline, "usd")}`
                        : undefined} />
              ) : null}
              <Stat label="Findings" value={report.findings.length}
                    sub={`${byLevel("high")} high · ${byLevel("medium")} medium · ${byLevel("low")} low`} />
              <Stat label="Checked, not a cause" value={report.not_causes.length} sub="hypotheses the data did not support" />
              <Stat label="Blocked by the verifier" value={report.insufficient.length} sub="claims left unresolved" />
            </dl>
            {report.provenance.runs.map((r) => <VerifierNote key={r.run_id} runId={r.run_id} />)}
            <Summary text={report.summary} />
            {report.revenue_split ? <SplitBar split={report.revenue_split} /> : null}
            <div>
              <h3 className="mb-3 text-base font-semibold text-ink">Findings</h3>
              <div className="grid gap-3">
                {report.findings.map((f) => <FindingCard key={f.id} f={f} />)}
              </div>
              <Outcomes notCauses={report.not_causes} insufficient={report.insufficient} />
            </div>
            <Provenance report={report} replay={!!health?.sample_mode} />
          </>
        ) : null}
      </section>
    </div>
  );
}
