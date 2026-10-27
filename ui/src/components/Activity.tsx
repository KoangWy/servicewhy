import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import { createPortal } from "react-dom";
import { formatElapsed, liveElapsed, useActivity, useNow } from "../activity";
import type { Activity, ActiveRun, ActivityEvent, RunKind, Stage } from "../types";
import { Badge, btnSecondary, linkAction } from "./common";

const STAGES: Stage[] = ["Planner", "Investigator", "Verifier", "Writer"];
const FEED_MAX = 12;
const KIND_LABEL: Record<RunKind, string> = { ask: "Ask", report: "Report", drilldown: "Drill-down" };

export type StepState = "done" | "active" | "pending";

/** Steps before the current stage are done, the current one is active, later ones pending: a retry back to an earlier stage re-opens it. */
export function stepStates(stage: Stage | null): StepState[] {
  const at = stage ? STAGES.indexOf(stage) : -1;
  return STAGES.map((_, i) => (at < 0 ? "pending" : i < at ? "done" : i === at ? "active" : "pending"));
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  // motion-safe: with reduced motion the arc stays put as a static glyph.
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className={`${className} shrink-0 motion-safe:animate-spin`}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

const STEP_LABEL: Record<StepState, string> = { done: "done", active: "in progress", pending: "pending" };

export function Stepper({ stage }: { stage: Stage | null }) {
  const states = stepStates(stage);
  return (
    <ol aria-label="Progress" className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
      {STAGES.map((s, i) => (
        <li key={s} data-state={states[i]} aria-current={states[i] === "active" ? "step" : undefined} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={`inline-flex size-5 items-center justify-center rounded-full border text-[11px] font-semibold ${
              states[i] === "done" ? "border-ok-line bg-ok-bg text-ok-fg"
              : states[i] === "active" ? "border-accent-ink/40 bg-accent-soft text-accent-ink"
              : "border-line-strong text-faint"
            }`}
          >
            {states[i] === "done" ? "✓" : states[i] === "active" ? <Spinner className="size-3" /> : i + 1}
          </span>
          <span className={states[i] === "active" ? "font-semibold text-ink" : states[i] === "done" ? "text-muted" : "text-faint"}>{s}</span>
          <span className="sr-only">: {STEP_LABEL[states[i]]}</span>
        </li>
      ))}
    </ol>
  );
}

const EVENT_STYLE: Record<string, string> = {
  block: "border-l-bad-fg bg-bad-bg/60",
  retry: "border-l-warn-fg bg-warn-bg/60",
};

/** Newest line last. It follows the end unless the reader scrolled up. Not a live region: the stage text is. */
export function Feed({ events }: { events: ActivityEvent[] }) {
  const box = useRef<HTMLDivElement | null>(null);
  const follow = useRef(true);
  const shown = events.slice(-FEED_MAX);
  useLayoutEffect(() => {
    const el = box.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [events]);
  return (
    <div
      ref={box}
      role="region"
      aria-label="Recent steps"
      tabIndex={0}
      onScroll={(e) => {
        const el = e.currentTarget;
        follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
      className="max-h-44 overflow-y-auto rounded-control border border-line bg-surface-2/60 p-2 font-mono text-xs leading-relaxed"
    >
      {shown.length ? (
        <ol className="space-y-0.5">
          {shown.map((e, i) => (
            <li key={`${e.at}-${i}`} data-event={e.event} className={`whitespace-pre-wrap break-words border-l-2 pl-2 text-muted ${EVENT_STYLE[e.event] ?? "border-l-transparent"}`}>
              {e.event === "block" || e.event === "retry" ? <strong className="mr-1.5 font-bold uppercase text-ink">[{e.event}]</strong> : null}
              <span className="font-semibold text-ink">{e.agent}</span>
              {"  "}
              <span>{e.action}</span>
              {"  "}
              <span>{e.summary}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-muted">No steps yet.</p>
      )}
    </div>
  );
}

function Count({ label, value, alert }: { label: string; value: number; alert?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`text-base font-semibold tabular-nums ${alert && value > 0 ? "text-bad-fg" : "text-ink"}`}>{value}</dd>
    </div>
  );
}

/** One running investigation, the way Claude Code shows a task: where it is, what it is doing, the last steps. */
export function RunProgress({ run, receivedAt, now, showQuestion = true, live = false }: { run: ActiveRun; receivedAt: number; now: number; showQuestion?: boolean; live?: boolean }) {
  const elapsed = liveElapsed(run.elapsed_s, receivedAt, now);
  return (
    <div className="space-y-3" data-testid="run-progress">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Badge tone="accent">{KIND_LABEL[run.kind] ?? run.kind}</Badge>
        <span className="text-sm tabular-nums text-muted" data-testid="run-elapsed">{formatElapsed(elapsed)}</span>
        <p aria-live={live ? "polite" : undefined} className="text-sm text-ink">{run.stage ? `${run.stage} is working` : "Starting"}</p>
      </div>
      {showQuestion ? <p className="break-words text-sm font-medium text-ink">{run.question}</p> : null}
      <Stepper stage={run.stage} />
      <dl className="grid grid-cols-4 gap-2">
        <Count label="Queries" value={run.counts.queries} />
        <Count label="Model calls" value={run.counts.model_calls} />
        <Count label="Blocks" value={run.counts.blocks} alert />
        <Count label="Retries" value={run.counts.retries} />
      </dl>
      {run.model ? <p className="break-all text-xs text-muted">Model: <span className="font-mono">{run.model}</span></p> : null}
      <Feed events={run.recent_events} />
    </div>
  );
}

const newest = (runs: ActiveRun[]) => runs.reduce<ActiveRun | null>((a, r) => (!a || r.started_at >= a.started_at ? r : a), null);

/** What the pill says. Several runs: the newest one's stage; a report between its runs: the report itself. */
function pillSummary(d: Activity) {
  const run = newest(d.active);
  const job = d.report_job;
  const count = d.active.length || (job ? 1 : 0);
  if (!count) return null;
  const elapsed = run && !(run.kind === "report" && job) ? run.elapsed_s : job?.elapsed_s ?? run?.elapsed_s ?? 0;
  return { stage: run ? run.stage ?? "Starting" : "Weekly report", count, elapsed };
}

export function ActivityControl() {
  const { status, data, receivedAt, open, setOpen } = useActivity();
  const pill = useRef<HTMLButtonElement | null>(null);
  const summary = data ? pillSummary(data) : null;
  const now = useNow(open || !!summary);
  if (status !== "on" || !data) return null;

  const close = () => {
    setOpen(false);
    pill.current?.focus();
  };
  return (
    <>
      <button
        ref={pill}
        type="button"
        aria-expanded={open}
        aria-controls="activity-panel"
        aria-haspopup="dialog"
        onClick={() => (open ? close() : setOpen(true))}
        data-testid="activity-pill"
        className="inline-flex min-h-10 max-w-full items-center gap-2 rounded-control border border-line-strong bg-surface px-3 text-sm font-medium text-ink transition-colors duration-150 hover:bg-surface-2"
      >
        <span className="sr-only">Activity: </span>
        {summary ? <Spinner className="size-3.5 text-accent-ink" /> : <span aria-hidden="true" className="size-2 rounded-full bg-faint" />}
        <span aria-live="polite" className="min-w-0 truncate">
          {summary ? summary.stage : "Idle"}
          {summary && summary.count > 1 ? <span className="font-normal text-muted"> ({summary.count} running)</span> : null}
        </span>
        {summary ? <span className="font-normal tabular-nums text-muted" data-testid="pill-elapsed">{formatElapsed(liveElapsed(summary.elapsed, receivedAt, now))}</span> : null}
      </button>
      {/* In the body, not in the sidebar: a fixed panel inside the sidebar's scroller made focus() scroll the sidebar sideways. */}
      {open ? createPortal(<ActivityPanel data={data} receivedAt={receivedAt} now={now} anchor={pill} onClose={close} />, document.body) : null}
    </>
  );
}

function ActivityPanel({ data, receivedAt, now, anchor, onClose }: { data: Activity; receivedAt: number; now: number; anchor: RefObject<HTMLButtonElement | null>; onClose: () => void }) {
  const panel = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  // Desktop: a popover under the pill, kept inside the viewport. Mobile ignores the position (bottom sheet).
  useLayoutEffect(() => {
    const place = () => {
      const r = anchor.current?.getBoundingClientRect();
      if (r) setPos({ top: r.bottom + 8, left: Math.max(8, Math.min(r.left, window.innerWidth - 416 - 8)) });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [anchor]);

  // The panel re-renders every second; focus and the key listener are set up once.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    panel.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const running = data.active.length;
  const job = data.report_job;
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 md:bg-transparent" onClick={onClose} aria-hidden="true" data-testid="activity-backdrop" />
      <div
        id="activity-panel"
        ref={panel}
        role="dialog"
        aria-label="Activity"
        tabIndex={-1}
        style={{ "--pop-top": `${pos.top}px`, "--pop-left": `${pos.left}px` } as CSSProperties}
        className="fixed inset-x-0 bottom-0 z-50 max-h-[85dvh] overflow-y-auto overscroll-contain rounded-t-card border border-line-strong bg-surface p-4 shadow-xl outline-none md:inset-x-auto md:bottom-auto md:left-[var(--pop-left)] md:top-[var(--pop-top)] md:max-h-[calc(100dvh-var(--pop-top)-1rem)] md:w-[26rem] md:rounded-card"
      >
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">Activity</h2>
          <button type="button" onClick={onClose} className={`${btnSecondary} min-h-9 px-3`}>Close</button>
        </div>
        <p aria-live="polite" className="mt-1 text-sm text-muted">
          {running ? `${running} running` : job ? "A weekly report is being generated." : "Nothing is running."}
        </p>

        {job ? (
          <p className="mt-3 rounded-control border border-line bg-surface-2/60 px-3 py-2 text-sm text-muted">
            Weekly report in progress: <span className="tabular-nums text-ink">{formatElapsed(liveElapsed(job.elapsed_s, receivedAt, now))}</span>. It takes several minutes.
          </p>
        ) : null}

        {running ? (
          <ul className="mt-3 space-y-3">
            {data.active.map((r) => (
              <li key={r.run_id} className="rounded-card border border-line p-3">
                <RunProgress run={r} receivedAt={receivedAt} now={now} />
                <a href={`#/trace/${r.run_id}`} onClick={onClose} className={`${linkAction} mt-3`}>Open full trace →</a>
              </li>
            ))}
          </ul>
        ) : null}

        <h3 className="mt-5 text-sm font-semibold text-ink">Recent</h3>
        {data.recent.length ? (
          <ul className="mt-2 divide-y divide-line">
            {data.recent.slice(0, 10).map((r) => (
              <li key={r.run_id} className="py-2">
                <a href={`#/trace/${r.run_id}`} onClick={onClose} className="block rounded-sm hover:bg-surface-2/60">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Badge tone={r.status === "success" ? "ok" : "bad"}>{r.status}</Badge>
                    <span className="text-xs tabular-nums text-muted">{formatElapsed(r.elapsed_s)}</span>
                    <span className="text-xs text-faint">{KIND_LABEL[r.kind as RunKind] ?? r.kind}</span>
                  </span>
                  <span className="mt-1 block break-words text-sm text-ink">{r.question}</span>
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted">No finished runs yet.</p>
        )}
      </div>
    </>
  );
}

/**
 * The inline wait indicator of Ask and the Dashboard. The elapsed time is the caller's own clock, so it works without
 * /activity; when /activity knows the runs, their stepper, counters and feed are shown too.
 */
export function WaitingProgress({ label, startedAt, runs, receivedAt, showQuestion = false, note }: { label: string; startedAt: number; runs: ActiveRun[]; receivedAt: number; showQuestion?: boolean; note?: string }) {
  const now = useNow(true);
  return (
    <div data-testid="waiting" className="space-y-4 rounded-card border border-line bg-surface-2/60 p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Spinner className="size-4 text-accent-ink" />
        <p role="status" className="text-sm font-medium text-ink">{label}</p>
        <span className="text-sm tabular-nums text-muted" data-testid="waiting-elapsed">{formatElapsed((now - startedAt) / 1000)}</span>
      </div>
      {note ? <p className="text-sm text-muted">{note}</p> : null}
      {runs.map((r) => (
        <div key={r.run_id} className="border-t border-line pt-4">
          <RunProgress run={r} receivedAt={receivedAt} now={now} showQuestion={showQuestion} live />
        </div>
      ))}
    </div>
  );
}
