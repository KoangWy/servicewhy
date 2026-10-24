import { useEffect, useState } from "react";
import { api } from "../api";
import type { Health, Report, RunResponse } from "../types";
import { Answer } from "./Answer";
import { Cited, FindingCard, Outcomes, SplitBar } from "./common";

const SUGGESTED = [
  "Why did Saturday dinner revenue drop 18%?",
  "Is the kitchen slow on Saturdays?",
  "Why do tables reset so slowly late evening?",
  "Who is our worst server?",
];

export function ReportScreen({ go, health }: { go: (p: string) => void; health: Health | null }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RunResponse | null>(null);

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
  return (
    <div>
      <section className="panel">
        <h2>Ask why</h2>
        <form className="ask" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask(question.trim()); }}>
          <input aria-label="question" value={question} placeholder="Why did Saturday dinner revenue drop 18%?"
                 onChange={(e) => setQuestion(e.target.value)} />
          <button disabled={busy || !question.trim()}>{busy ? "Investigating…" : "Ask"}</button>
        </form>
        <div className="chips">
          {suggestions.map((q) => <button key={q} className="chip" onClick={() => ask(q)}>{q}</button>)}
        </div>
        {run ? <Answer run={run} go={go} /> : null}
      </section>

      <section className="panel">
        <h2>Weekly report{report ? `: ${report.period.start} to ${report.period.end}` : ""}</h2>
        {error ? <div className="answer error">{error}</div> : null}
        {!report && !error ? <div className="muted">Generating the report (a batch run of the same agent)…</div> : null}
        {report ? (
          <>
            <p className="summary"><Cited text={report.summary} /></p>
            {report.revenue_split ? <SplitBar split={report.revenue_split} /> : null}
            <div className="cards">
              {report.findings.map((f) => <FindingCard key={f.id} f={f} onOpen={(id) => go(`/finding/${id}`)} />)}
            </div>
            <Outcomes notCauses={report.not_causes} insufficient={report.insufficient} />
            <details className="provenance">
              <summary>Data provenance</summary>
              <p>{report.provenance.data}</p>
              <p>Channel: {report.provenance.channel} · Model: {report.provenance.model}</p>
              <ul>
                {report.provenance.runs.map((r) => (
                  <li key={r.run_id}>
                    <button className="link" onClick={() => go(`/trace/${r.run_id}`)}>{r.run_id}</button>: {r.question}
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : null}
      </section>
    </div>
  );
}
