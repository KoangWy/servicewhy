import type { RunResponse } from "../types";
import { Cited, FindingCard, Outcomes, SplitBar } from "./common";

export function Answer({ run, go }: { run: RunResponse; go: (path: string) => void }) {
  if (run.status === "error" || !run.output) {
    return (
      <div className="answer error">
        <b>{run.error?.type}:</b> {run.error?.message}
        {run.error?.available_questions ? (
          <ul className="suggest">
            {run.error.available_questions.map((q) => <li key={q}>{q}</li>)}
          </ul>
        ) : null}
      </div>
    );
  }
  const o = run.output;
  return (
    <div className={`answer type-${o.answer_type}`}>
      <div className="answer-head">
        <span className="badge">{o.answer_type.replace("_", " ")}</span>
        <button className="link" onClick={() => go(`/trace/${run.run_id}`)}>Evidence &amp; trace →</button>
      </div>
      <p className="summary"><Cited text={o.summary} /></p>
      {o.revenue_split ? <SplitBar split={o.revenue_split} /> : null}
      <div className="cards">
        {o.findings.map((f) => <FindingCard key={f.id} f={f} onOpen={(id) => go(`/finding/${id}`)} />)}
      </div>
      <Outcomes notCauses={o.not_causes} insufficient={o.insufficient} />
    </div>
  );
}
