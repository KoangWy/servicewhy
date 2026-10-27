import { useCallback, useEffect, useRef, useState } from "react";
import { useActivity, useActivityBoost } from "../activity";
import { api, isApiError } from "../api";
import type { Health, Report } from "../types";
import { WaitingProgress } from "./Activity";
import { btnPrimary, fmt, FindingCard, Outcomes, panel, SplitBar, Summary } from "./common";
import { VerifierNote } from "./VerifierNote";

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

const REPORT_POLL_MS = 3000;

export function ReportScreen({ health }: { health: Health | null }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  // null until GET /reports answered; true when it answered with no report yet.
  const [empty, setEmpty] = useState<boolean | null>(null);
  const [pressedAt, setPressedAt] = useState<number | null>(null);
  const [conflictAt, setConflictAt] = useState<number | null>(null);
  const pressed = useRef(false);
  const { data, receivedAt } = useActivity();

  const load = useCallback(async (): Promise<boolean> => {
    const list = await api.listReports();
    if (!list.length) return false;
    setReport(await api.report(list[list.length - 1].report_id));
    setEmpty(false);
    return true;
  }, []);

  // Reading only: a report is never created from an effect, so StrictMode or a reload cannot start a second generation.
  useEffect(() => {
    load().then((found) => !found && setEmpty(true)).catch((e) => setError(String(e)));
  }, [load]);

  // The API says a generation is running (this tab, another tab, before a reload).
  const reportRuns = data?.active.filter((r) => r.kind === "report") ?? [];
  const job = data?.report_job ?? null;
  const generating = !report && empty === true && (pressedAt != null || !!job || reportRuns.length > 0);
  useActivityBoost(generating);

  useEffect(() => {
    if (!generating) return;
    const id = setInterval(() => load().catch(() => {}), REPORT_POLL_MS);
    return () => clearInterval(id);
  }, [generating, load]);

  // After a 409 the generation belongs to someone else. Once a poll newer than the 409 shows no job any more, stop waiting
  // for it (a last look at /reports first); without /activity the 409 keeps the progress state, which still polls /reports.
  useEffect(() => {
    if (conflictAt == null || !data || receivedAt <= conflictAt || job || reportRuns.length) return;
    load().then((found) => {
      if (found) return;
      setConflictAt(null);
      setPressedAt(null);
    }).catch(() => {});
  }, [conflictAt, data, receivedAt, job, reportRuns.length, load]);

  const generate = async () => {
    if (pressed.current) return;
    pressed.current = true;
    setPressedAt(Date.now());
    setError(null);
    try {
      const body = await api.createReport();
      if (isApiError(body)) {
        // 409 ReportInProgress means someone else started it: wait for it like our own.
        if (body.error.type !== "ReportInProgress") throw new Error(`${body.error.type}: ${body.error.message}`);
        pressed.current = false;
        setConflictAt(Date.now());
        return;
      }
      if (!(await load())) throw new Error("The report was created but could not be found.");
    } catch (e) {
      setError(String(e));
      setPressedAt(null);
      pressed.current = false;
    }
  };

  const rs = report?.revenue_split;
  const byLevel = (l: string) => report?.findings.filter((f) => f.confidence === l).length ?? 0;
  return (
    <div className="space-y-12">
      <section className={`${panel} flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between`} aria-labelledby="ask-h">
        <div>
          <h2 id="ask-h" className="text-lg font-semibold text-ink">Ask why</h2>
          <p className="mt-1 text-sm text-muted">Ask about a change in revenue or service. The verifier blocks any claim the data does not support.</p>
        </div>
        <a href="#/ask" className={`${btnPrimary} shrink-0`}>Ask a question</a>
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
        {!report && empty === null && !error ? <p role="status" className="text-sm text-muted">Loading the report…</p> : null}
        {!report && empty && !generating ? (
          <div className={panel}>
            <p className="font-medium text-ink">No weekly report yet</p>
            <p className="mt-1 text-sm text-muted">Generating one runs the same agent in a batch over the week's data. It takes several minutes.</p>
            <button type="button" onClick={generate} className={`${btnPrimary} mt-4`}>Generate weekly report</button>
          </div>
        ) : null}
        {generating ? (
          <WaitingProgress
            label="Generating the weekly report…"
            startedAt={job ? receivedAt - job.elapsed_s * 1000 : pressedAt ?? Date.now()}
            receivedAt={receivedAt}
            runs={reportRuns}
            showQuestion
            note="This takes several minutes. You can leave this page; the report appears here when it is ready."
          />
        ) : null}
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
