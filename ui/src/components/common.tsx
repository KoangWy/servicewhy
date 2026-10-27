import type { ReactNode } from "react";
import { Logo } from "./Brand";
import type { Finding, Health, NotCause, Insufficient, RevenueSplit } from "../types";

// Shared class strings, so every screen draws controls and surfaces the same way.
export const panel = "rounded-card border border-line bg-surface p-5 sm:p-6";
const btn =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-control px-4 text-sm font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50";
export const btnPrimary = `${btn} border border-transparent bg-accent text-accent-fg hover:bg-accent/90`;
export const btnSecondary = `${btn} border border-line-strong bg-surface text-ink hover:bg-surface-2`;
export const linkAction =
  "inline-flex items-center gap-1 rounded-sm text-sm font-medium text-accent-ink underline-offset-4 hover:underline";
export const field =
  "min-h-10 w-full min-w-0 rounded-control border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-faint disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-muted";

// Units are shown only where the payload carries them: effect deltas already include them, and metric names end in
// _min (minutes), _rate or _share (a fraction), or contain "revenue" (the findings print revenue in $).
const unitOf = (metric: string) =>
  /_min$/.test(metric) ? "min" : /_(rate|share)$/.test(metric) ? "share" : /revenue/.test(metric) ? "usd" : undefined;

export function fmt(v: number | null, unit?: string): string {
  if (v == null) return "n/a";
  if (unit === "share") return `${(v * 100).toFixed(1)}%`;
  if (unit === "usd") return v.toLocaleString("en-US", { style: "currency", currency: "USD" });
  const n = Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
  return unit ? `${n} ${unit}` : n;
}

export const fmtMetric = (metric: string, v: number | null) => fmt(v, unitOf(metric));
export const metricLabel = (metric: string) => metric.replace(/_/g, " ");

type Tone = "ok" | "warn" | "bad" | "neutral" | "accent";

const TONES: Record<Tone, string> = {
  ok: "border-ok-line bg-ok-bg text-ok-fg",
  warn: "border-warn-line bg-warn-bg text-warn-fg",
  bad: "border-bad-line bg-bad-bg text-bad-fg",
  neutral: "border-neutral-line bg-neutral-bg text-neutral-fg",
  accent: "border-accent-ink/30 bg-accent-soft text-accent-ink",
};

// The "badge" class is a stable hook for tests; the look comes from the utilities.
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`badge inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

const LEVEL: Record<Finding["confidence"], { bars: number; tone: Tone }> = {
  high: { bars: 3, tone: "ok" },
  medium: { bars: 2, tone: "warn" },
  low: { bars: 1, tone: "neutral" },
};

/** Bar count carries the level in shape as well as colour; the text label stays. */
export function Confidence({ level }: { level: Finding["confidence"] }) {
  const { bars, tone } = LEVEL[level];
  return (
    <Badge tone={tone}>
      <span aria-hidden="true" className="inline-flex items-end gap-0.5">
        {[1, 2, 3].map((i) => (
          <span key={i} className={`w-0.5 rounded-full bg-current ${i <= bars ? "" : "opacity-25"} ${["h-1.5", "h-2", "h-2.5"][i - 1]}`} />
        ))}
      </span>
      {level} confidence
    </Badge>
  );
}

const STATUS_TONE: Record<Finding["status"], Tone> = { proposed: "neutral", approved: "ok", rejected: "bad" };

export function Status({ status }: { status: Finding["status"] }) {
  return <Badge tone={STATUS_TONE[status]}>{status}</Badge>;
}

/** Turns "[evd_…]" and "[fnd_…]" citations into small tags so numbers stay visibly tied to evidence. */
export function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]*(?:evd|fnd)_[^\]]*\])/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("[") && /(?:evd|fnd)_/.test(p) ? (
          <span
            key={i}
            title={p.includes("fnd_") ? "finding id" : "evidence id"}
            className="ml-1 whitespace-nowrap rounded border border-line bg-surface-2 px-1 align-baseline font-mono text-[11px] text-muted"
          >
            {p.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

/** The model's summary, unchanged: its first sentence is the lead and each further sentence gets its own line. */
export function Summary({ text }: { text: string }) {
  const [lead, ...rest] = text.split(/(?<=\.)\s+(?=[A-Z])/);
  return (
    <div>
      <p className="max-w-3xl text-pretty text-lg/7 font-medium text-ink sm:text-xl/8">
        <Cited text={lead} />
      </p>
      {rest.length ? (
        <ul className="mt-4 max-w-3xl space-y-2 border-l border-line pl-4 text-[0.9375rem] leading-relaxed text-muted">
          {rest.map((s, i) => (
            <li key={i}>
              <Cited text={s} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function SyntheticBanner({ mode, replay }: { mode?: string; replay?: boolean }) {
  return (
    <div className="border-b border-line bg-surface-2" role="note" data-testid="synthetic-label">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-muted sm:px-6">
        <span>
          <strong className="font-semibold text-ink">Synthetic data:</strong> a seeded simulator generates every guest,
          ticket and shift. No real people or restaurant.
        </span>
        {mode ? (
          <span data-testid="mode-label" className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${replay ? TONES.warn : TONES.neutral}`}>
            {mode}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function SplitBar({ split }: { split: RevenueSplit }) {
  if (split.volume_share == null || split.change_rel == null) return null;
  const vol = Math.round(split.volume_share * 100);
  const change = (split.change_rel * 100).toFixed(0);
  return (
    <div className="rounded-card border border-line bg-surface-2/60 p-4" aria-label="revenue change split">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-2xl font-semibold tabular-nums text-ink">
          {split.change_rel > 0 ? "+" : ""}
          {change}%
        </span>
        <span className="text-sm text-muted">revenue change vs baseline, split by the verifier (rule V4)</span>
        {split.decoy_dominant ? <Badge tone="warn">fewer customers dominate: service findings downgraded</Badge> : null}
      </div>
      <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-line" role="img" aria-label={`fewer parties ${vol}%, revenue per party ${100 - vol}%`}>
        <div className="bg-faint" style={{ width: `${vol}%` }} />
        <div className="bg-accent" style={{ width: `${100 - vol}%` }} />
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className="size-2.5 rounded-sm bg-faint" />
          <dt className="text-muted">Fewer parties</dt>
          <dd className="font-medium tabular-nums text-ink">{vol}%</dd>
        </div>
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className="size-2.5 rounded-sm bg-accent" />
          <dt className="text-muted">Revenue per party</dt>
          <dd className="font-medium tabular-nums text-ink">{100 - vol}%</dd>
        </div>
      </dl>
    </div>
  );
}

export function FindingCard({ f }: { f: Finding }) {
  return (
    <a
      href={`#/finding/${f.id}`}
      className="group block rounded-card border border-line bg-surface p-4 transition-colors duration-150 hover:border-line-strong hover:bg-surface-2/60 sm:p-5"
    >
      <span className="flex flex-wrap items-center gap-2">
        <Confidence level={f.confidence} />
        <Status status={f.status} />
      </span>
      <span className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-6">
        <span className="block font-medium leading-snug text-ink">{f.cause_hypothesis}</span>
        <span className="block sm:text-right">
          <span className="block text-2xl font-semibold leading-none tabular-nums text-ink">{f.effect_size.delta}</span>
          <span className="mt-1 block text-sm tabular-nums text-muted">
            {f.effect_size.relative ? `${f.effect_size.relative} · ` : ""}
            {metricLabel(f.effect_size.metric)}
          </span>
        </span>
      </span>
      <span className="mt-4 flex items-center justify-between border-t border-line pt-3 text-sm text-muted">
        <span>{f.evidence.length} evidence items</span>
        <span className="font-medium text-accent-ink group-hover:underline">View finding →</span>
      </span>
    </a>
  );
}

export function Outcomes({ notCauses, insufficient }: { notCauses: NotCause[]; insufficient: Insufficient[] }) {
  if (!notCauses.length && !insufficient.length) return null;
  return (
    <section className="mt-8">
      <h3 className="mb-3 text-base font-semibold text-ink">Other checks</h3>
      <div className="grid gap-2">
        {notCauses.map((n, i) => (
          <div key={`n${i}`} className="rounded-control border border-line bg-surface px-4 py-3 text-sm">
            <div className="font-medium text-ink">Checked, not a cause</div>
            <div className="mt-0.5 text-muted">{n.negative || n.statement}</div>
            {n.evidence.length ? (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted">
                {n.evidence.map((e) => (
                  <span key={e.evidence_id}>
                    {fmt(e.value, e.unit)} vs {fmt(e.baseline, e.unit)} baseline · n={e.n}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {insufficient.map((b, i) => (
          <div key={`b${i}`} className="rounded-control border border-bad-line bg-bad-bg px-4 py-3 text-sm">
            <div className="font-medium text-bad-fg">Blocked by the verifier</div>
            <div className="mt-0.5 text-ink">{b.statement}</div>
            <div className="mt-1 text-xs text-muted">{b.reasons.join("; ")}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Footer: credits the team, names the two sponsor technologies and says, from /health, whether anything is live. */
export function PoweredBy({ health, failed }: { health: Health | null; failed: boolean }) {
  let tone: Tone = "neutral";
  let status = "Checking the API…";
  if (failed) {
    status = "The API did not answer /health, so nothing is claimed about which services are running.";
  } else if (health?.sample_mode) {
    tone = "warn";
    status = "Recorded replay: no Zetaris query and no model call is made while you use this page. Each run's trace shows what was executed when it was recorded.";
  } else if (health?.zetaris === "up") {
    status = `Zetaris answered the health check. Model: ${health.model}.`;
  } else if (health?.zetaris === "down") {
    tone = "bad";
    status = "Zetaris did not answer the health check.";
  } else if (health?.zetaris === "local") {
    status = `Local simulator store (SQLite): Zetaris is not in use. Model: ${health.model}.`;
  }
  return (
    <footer className="mt-16 border-t border-line py-8 text-sm text-muted" aria-label="Provenance">
      <div className="flex items-start gap-3" data-testid="team-credit">
        <Logo className="mt-0.5 size-7" />
        <div className="min-w-0">
          <p className="text-ink">
            <span className="font-semibold">ServiceWhy</span> was built by <span className="font-semibold">Team Irigo</span>:
            {" "}Lê Quang Minh Khoa and Nguyễn Quang Huy.
          </p>
          <p className="mt-0.5">Open Agent Hackathon 2026 · Track 02, The Agent That Can Explain Why · All data is synthetic.</p>
        </div>
      </div>
      <div className="mt-6 grid gap-5 sm:grid-cols-2 sm:gap-8">
        <div>
          <h2 className="font-semibold text-ink">Powered by Zetaris</h2>
          <p className="mt-1">Federated SQL over the two data stores (PostgreSQL and Parquet on MinIO). The investigator and the verifier both query through it.</p>
        </div>
        <div>
          <h2 className="font-semibold text-ink">Powered by Meterless</h2>
          <p className="mt-1">In FULL mode the model calls go through Meterless Nightshift. World-model state with provenance is an in-repo engine built on the Meterless reference architecture; each state write is a traced event.</p>
        </div>
      </div>
      <p className="mt-5 flex flex-wrap items-start gap-x-3 gap-y-2">
        <Badge tone={tone}>{health?.sample_mode ? "Recorded replay" : failed ? "Status unknown" : health ? `Zetaris ${health.zetaris}` : "Checking"}</Badge>
        <span className="min-w-0 flex-1 basis-64">{status}</span>
      </p>
    </footer>
  );
}
