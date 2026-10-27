import { useEffect, useState } from "react";
import { api } from "../api";
import type { RunSummary } from "../types";
import { Badge, linkAction, panel } from "./common";

export function RunsScreen() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.runs().then((r) => setRuns([...r].reverse())).catch((e) => setError(String(e)));
  }, []);

  return (
    <section aria-labelledby="runs-h" className="space-y-4">
      <div>
        <h2 id="runs-h" className="text-lg font-semibold text-ink">Runs</h2>
        <p className="mt-0.5 text-sm text-muted">Every question answered since the API started, newest first. Open one to see its evidence and trace.</p>
      </div>
      {error ? <div role="alert" className="rounded-card border border-bad-line bg-bad-bg p-4 text-sm text-bad-fg">Could not load runs: {error}</div> : null}
      {!runs && !error ? <p role="status" className="text-sm text-muted">Loading runs…</p> : null}
      {runs && !runs.length ? (
        <div className={panel}>
          <p className="text-ink">No runs yet.</p>
          <p className="mt-1 text-sm text-muted">Runs appear here after you ask a question or generate a report.</p>
          <a href="#/ask" className={`${linkAction} mt-3`}>Ask a question →</a>
        </div>
      ) : null}
      {runs?.length ? (
        <ul className="grid gap-2">
          {runs.map((r) => (
            <li key={r.run_id}>
              <a href={`#/trace/${r.run_id}`} className="block rounded-card border border-line bg-surface p-4 transition-colors duration-150 hover:border-line-strong hover:bg-surface-2/60">
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <Badge tone={r.status === "success" ? "ok" : "bad"}>{r.status}</Badge>
                  <span className="font-mono text-xs text-muted [overflow-wrap:anywhere]">{r.run_id}</span>
                </span>
                <span className="mt-2 block font-medium text-ink">{r.question ?? "No question recorded"}</span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
