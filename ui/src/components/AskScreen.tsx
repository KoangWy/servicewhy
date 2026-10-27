import { useState } from "react";
import { api } from "../api";
import type { Health, RunResponse } from "../types";
import { Answer } from "./Answer";
import { btnPrimary, field, panel } from "./common";

const SUGGESTED = [
  "Why did Saturday dinner revenue drop 18%?",
  "Is the kitchen slow on Saturdays?",
  "Why do tables reset so slowly late evening?",
  "Who is our worst server?",
];
const VISIBLE_SUGGESTIONS = 4;

const chip =
  "rounded-full border border-line bg-surface-2 px-3 py-1.5 text-left text-sm text-ink transition-colors duration-150 hover:border-line-strong disabled:opacity-50";

/** SAMPLE mode answers only recorded questions; a miss lists them instead of showing a bare error. */
function SampleMiss({ run, onAsk }: { run: RunResponse; onAsk: (q: string) => void }) {
  const questions = run.error?.available_questions ?? [];
  return (
    <div role="alert" className="rounded-card border border-warn-line bg-warn-bg p-4 text-sm">
      <p className="font-medium text-warn-fg">That question was not recorded.</p>
      <p className="mt-1 text-ink">SAMPLE mode replays recorded runs, so it can only answer the questions below. To ask anything else, run the live stack (path B in the README).</p>
      {questions.length ? (
        <ul className="mt-3 flex flex-col gap-1.5">
          {questions.map((q) => (
            <li key={q}>
              <button type="button" onClick={() => onAsk(q)} className="rounded-control border border-line bg-surface px-3 py-2 text-left text-ink transition-colors duration-150 hover:bg-surface-2">
                {q}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function AskScreen({ health }: { health: Health | null }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RunResponse | null>(null);
  const [showAll, setShowAll] = useState(false);

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
  return (
    <section className={panel} aria-labelledby="ask-h">
      <h2 id="ask-h" className="text-lg font-semibold text-ink">Ask why</h2>
      <p className="mt-1 text-sm text-muted">Ask about a change in revenue or service. The verifier blocks any claim the data does not support.</p>
      <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask(question.trim()); }}>
        <input className={field} aria-label="question" value={question} placeholder="Why did Saturday dinner revenue drop 18%?" onChange={(e) => setQuestion(e.target.value)} />
        <button className={`${btnPrimary} sm:w-28`} disabled={busy || !question.trim()}>{busy ? "Investigating…" : "Ask"}</button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {shown.map((q) => (
          <button key={q} type="button" onClick={() => ask(q)} disabled={busy} className={chip}>{q}</button>
        ))}
        {suggestions.length > VISIBLE_SUGGESTIONS ? (
          <button type="button" aria-expanded={showAll} onClick={() => setShowAll(!showAll)} className="rounded-full px-3 py-1.5 text-sm font-medium text-accent-ink hover:underline">
            {showAll ? "Show fewer" : `Show ${suggestions.length - VISIBLE_SUGGESTIONS} more`}
          </button>
        ) : null}
      </div>
      <div aria-live="polite">
        {busy ? <p role="status" className="mt-6 text-sm text-muted">Investigating: planning, querying, then verifying every number…</p> : null}
        {run ? (
          <div className="mt-6 border-t border-line pt-6">
            {run.error?.type === "SampleModeMiss" ? <SampleMiss run={run} onAsk={ask} /> : <Answer run={run} onAsk={ask} />}
          </div>
        ) : null}
      </div>
    </section>
  );
}
