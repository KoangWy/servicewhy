import type { Finding, NotCause, Insufficient, RevenueSplit } from "../types";

export function SyntheticBanner({ mode }: { mode?: string }) {
  return (
    <div className="synthetic" role="note" data-testid="synthetic-label">
      Synthetic data: a seeded simulator generates every guest, ticket and shift. No real people or restaurant.
      {mode ? <span className="mode"> · {mode}</span> : null}
    </div>
  );
}

export function Confidence({ level }: { level: Finding["confidence"] }) {
  return <span className={`badge conf-${level}`}>{level} confidence</span>;
}

export function Status({ status }: { status: Finding["status"] }) {
  return <span className={`badge status-${status}`}>{status}</span>;
}

/** Turns "[evd_…]" citations into small tags so numbers stay visibly tied to evidence. */
export function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]*evd_[^\]]*\])/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("[") && p.includes("evd_") ? (
          <span key={i} className="cite" title="evidence id">
            {p.slice(1, -1)}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

export function SplitBar({ split }: { split: RevenueSplit }) {
  if (split.volume_share == null || split.change_rel == null) return null;
  const vol = Math.round(split.volume_share * 100);
  return (
    <div className="split" aria-label="revenue change split">
      <div className="split-title">
        Revenue change {(split.change_rel * 100).toFixed(0)}% vs baseline, split by the verifier (rule V4)
        {split.decoy_dominant ? " · fewer customers dominate: service findings downgraded" : ""}
      </div>
      <div className="split-bar">
        <div className="split-vol" style={{ width: `${vol}%` }}>{vol >= 12 ? `fewer parties ${vol}%` : ""}</div>
        <div className="split-spend" style={{ width: `${100 - vol}%` }}>
          {100 - vol >= 12 ? `revenue per party ${100 - vol}%` : ""}
        </div>
      </div>
    </div>
  );
}

export function FindingCard({ f, onOpen }: { f: Finding; onOpen: (id: string) => void }) {
  return (
    <button className="card finding" onClick={() => onOpen(f.id)}>
      <div className="card-top">
        <Confidence level={f.confidence} />
        <Status status={f.status} />
      </div>
      <div className="cause">{f.cause_hypothesis}</div>
      <div className="effect">
        {f.effect_size.metric.replace(/_/g, " ")}: <b>{f.effect_size.delta}</b>
        {f.effect_size.relative ? ` (${f.effect_size.relative})` : ""} · {f.evidence.length} evidence items
      </div>
    </button>
  );
}

export function Outcomes({ notCauses, insufficient }: { notCauses: NotCause[]; insufficient: Insufficient[] }) {
  if (!notCauses.length && !insufficient.length) return null;
  return (
    <div className="outcomes">
      {notCauses.map((n, i) => (
        <div key={`n${i}`} className="outcome not-cause">
          <b>Checked, not a cause:</b> {n.negative || n.statement}
        </div>
      ))}
      {insufficient.map((b, i) => (
        <div key={`b${i}`} className="outcome blocked">
          <b>Blocked by the verifier:</b> {b.statement}
          <div className="reasons">{b.reasons.join("; ")}</div>
        </div>
      ))}
    </div>
  );
}
