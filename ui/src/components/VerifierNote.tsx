import { useEffect, useState } from "react";
import { api } from "../api";
import type { TraceEvent } from "../types";
import { Badge } from "./common";

// Plain-language names for the blocking rules in the README's verifier table (V4 and V5 never block a claim).
const RULE: Record<string, string> = { V1: "a number did not re-query", V2: "sample too small", V3: "no baseline to compare against" };

interface Block {
  reasons: string;
  why: string;
  retry?: string;
  outcome?: "pass" | "block";
}

/** Reads the verifier's blocks and widened retries out of a run's trace; empty when nothing was blocked. */
export function summariseVerifier(events: TraceEvent[]): Block[] {
  return events.flatMap((e, i) => {
    if (e.event !== "block") return [];
    const codes = [...new Set((e.output_summary.match(/\bV\d\b/g) || []))];
    const retry = events.find((r) => r.event === "retry" && r.input_summary === e.input_summary);
    const verdict = events.slice(i + 1).find((v) => v.action === "verdict" && v.input_summary === e.input_summary);
    return [{
      reasons: e.output_summary,
      why: codes.map((c) => RULE[c]).filter(Boolean).join(", "),
      retry: retry?.output_summary.replace(/^retry \d+: /, "").replace(/ -> /g, " → "),
      outcome: retry && (verdict?.verdict === "pass" || verdict?.verdict === "block") ? verdict.verdict : undefined,
    }];
  });
}

/** Surfaces the "block, then widened retry" behaviour next to the answer, linked to the full trace. */
export function VerifierNote({ runId }: { runId: string }) {
  const [blocks, setBlocks] = useState<Block[]>([]);
  useEffect(() => {
    let live = true;
    setBlocks([]);
    // The note is a convenience; if the trace cannot be read the trace link on the screen still reports that.
    api.trace(runId).then((t) => live && setBlocks(summariseVerifier(t.events))).catch(() => {});
    return () => { live = false; };
  }, [runId]);

  if (!blocks.length) return null;
  const retried = blocks.filter((b) => b.retry).length;
  return (
    <aside className="rounded-card border border-accent-ink/25 bg-accent-soft p-4 text-sm" aria-label="Verifier summary" data-testid="verifier-note">
      <div className="flex items-start gap-3">
        <Badge tone="accent">Verifier</Badge>
        <p className="min-w-0 flex-1 font-medium text-ink">
          Blocked {blocks.length} {blocks.length === 1 ? "hypothesis" : "hypotheses"}
          {retried ? `, then retried ${retried === blocks.length ? "" : `${retried} `}on a wider window` : ""}.
        </p>
      </div>
      <ul className="mt-2 space-y-2 text-muted">
        {blocks.map((b, i) => (
          <li key={i}>
            {b.why ? <span className="font-medium text-ink">{b.why}</span> : null}
            {b.why ? " " : null}
            <span className="tabular-nums">({b.reasons}).</span>
            {b.retry ? <> Retried: {b.retry}.</> : null}
            {b.outcome ? <> {b.outcome === "pass" ? "The claim passed on the wider window." : "Still blocked after the retry."}</> : null}
          </li>
        ))}
      </ul>
      <a href={`#/trace/${runId}`} className="mt-3 inline-block font-medium text-accent-ink underline-offset-4 hover:underline">See the trace →</a>
    </aside>
  );
}
