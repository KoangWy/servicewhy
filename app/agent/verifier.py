"""Verifier: blocks any claim the data does not support (SPEC §7).

Deterministic rules run in code, each one a trace event; the model adds one structured judgment
(block/pass + reason) and never recomputes numbers.

  V1  every value recomputed by an independent second query through the same federated surface
  V2  minimum sample per segment (block below N_BLOCK, downgrade below N_FULL)
  V3  a causal claim needs a contrast (baseline group present)
  V4  decoy split: if fewer customers explain >= DECOY_SHARE of a revenue drop, downgrade + force the split
  V5  more than MAX_RETRIES rejections -> "insufficient evidence"
"""
from __future__ import annotations

import json
from typing import Any

from app.metrics import METRICS

# Initial values (SPEC §7). Tuned once before the feature freeze, then published in the README.
THRESHOLDS = {"V1_tolerance": 0.02, "V2_n_block": 15, "V2_n_full": 30, "V4_decoy_share": 0.5, "V5_max_retries": 2}

SYSTEM = """You are the Verifier of ServiceWhy. You judge whether evidence supports a claim about a restaurant.
You never compute or restate numbers. Block when the contrast does not test the claim, when the effect could be
explained by something the evidence does not rule out, or when the claim says more than the evidence shows.
Return ONE JSON object: {"verdict": "pass" | "block", "reason": one sentence}."""

LEVELS = ("low", "medium", "high")


def downgrade(confidence: str) -> str:
    return LEVELS[max(0, LEVELS.index(confidence) - 1)]


def _close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


class Verifier:
    name = "Verifier"
    role = "Re-queries every number independently, enforces sample size, contrast and decoy rules, and can block"

    def __init__(self, investigator, model, context, trace):
        self.inv, self.model, self.context, self.trace = investigator, model, context, trace

    # ---- deterministic item checks -------------------------------------------------------------------
    def check_item(self, ev: dict, *, retry: int) -> dict[str, Any]:
        t = THRESHOLDS
        sql = self.inv.sql_for(ev["spec"], raw=True, independent=True)
        rows = self.inv._query(sql, purpose=f"V1 independent re-query of {ev['id']}", agent=self.name, retry=retry)
        re = self.inv.compute(ev["spec"], rows, raw=True)
        v1 = _close(re["value"], ev["value"], t["V1_tolerance"]) and _close(re["baseline"], ev["baseline"], t["V1_tolerance"])
        n_min = min(ev["n"], ev["n_baseline"]) if ev["baseline"] is not None else ev["n"]
        reasons = []
        if not v1:
            reasons.append(f"V1: re-query gave {re['value']!r}/{re['baseline']!r} vs reported "
                           f"{ev['value']!r}/{ev['baseline']!r} (> ±{t['V1_tolerance']:.0%})")
        if n_min < t["V2_n_block"]:
            reasons.append(f"V2: n={n_min} < {t['V2_n_block']}")
        result = {"evidence_id": ev["id"], "v1_pass": v1, "recomputed": {"value": re["value"], "baseline": re["baseline"]},
                  "n_min": n_min, "small_sample": t["V2_n_block"] <= n_min < t["V2_n_full"],
                  "blocked": bool(reasons), "reasons": reasons}
        self.trace.emit("verify", self.name, "check_evidence", input_summary=ev["id"],
                        output_summary=("blocked: " + "; ".join(reasons)) if reasons else
                        f"V1 re-query matches; V2 n={n_min}" + (" (small sample: downgrade)" if result["small_sample"] else ""),
                        query=sql, rows_used=len(rows), verdict="block" if reasons else "pass", retry_count=retry,
                        data=result)
        return result

    # ---- hypothesis verdict ------------------------------------------------------------------------
    def verify(self, hypothesis: dict, evidence: list[dict], *, retry: int) -> dict[str, Any]:
        checks = {e["id"]: self.check_item(e, retry=retry) for e in evidence}
        passed = [e for e in evidence if not checks[e["id"]]["blocked"]]
        causal = [e for e in passed if not e["descriptive"]]
        reasons = [r for c in checks.values() for r in c["reasons"]]
        verdict: dict[str, Any] = {"hypothesis_id": hypothesis["wm_id"], "checks": list(checks.values()),
                                   "passed_ids": [e["id"] for e in passed]}
        if not causal:
            return self._block(verdict, reasons or ["no evidence item survived verification"], retry)
        if not any(e["baseline"] is not None for e in causal):
            return self._block(verdict, ["V3: no contrast (baseline group missing) for a causal claim"], retry)
        supporting = [e for e in causal if e["supports"]]
        blocked_causal = [e for e in evidence if not e["descriptive"] and checks[e["id"]]["blocked"]]
        if supporting:
            status, confidence = "supported", self._confidence(supporting, checks)
        elif blocked_causal:
            return self._block(verdict, reasons, retry)  # cannot call it "not a cause" on partial evidence
        else:
            status, confidence = "rejected", None
        # model judgment over the World Model context (structured payload, not raw strings)
        ctx = self.context.build(intent="verify", hypothesis_id=hypothesis["wm_id"], evidence_ids=[e["id"] for e in passed])
        payload = {"claim": hypothesis["statement"], "proposed_status": status,
                   "evidence": [{"evidence_id": e["id"], "metric": e["metric"], "contrast": e["contrast"],
                                 "contrast_type": e["contrast_type"], "group": e.get("group"),
                                 "value": e["value"], "baseline": e["baseline"], "n": e["n"],
                                 "n_baseline": e["n_baseline"], "supports_claim": e["supports"],
                                 "small_sample": checks[e["id"]]["small_sample"], "descriptive": e["descriptive"]}
                                for e in ctx["evidence"]],
                   "context_trace": ctx["trace"]}
        judged, _ = self.model.complete_json("verifier", "Judge this claim.\n<<INPUT>>\n" +
                                             json.dumps(payload, sort_keys=True, default=str) + "\n<<END>>", SYSTEM)
        if str(judged.get("verdict", "")).lower() != "pass":
            return self._block(verdict, [f"model: {judged.get('reason', 'no reason given')}"], retry)
        verdict.update(status=status, confidence=confidence, blocked=False, model_reason=judged.get("reason", ""),
                       supporting_ids=[e["id"] for e in supporting])
        self.trace.emit("verify", self.name, "verdict", input_summary=hypothesis["wm_id"],
                        output_summary=f"pass -> {status}" + (f" ({confidence})" if confidence else "") +
                        f"; model: {judged.get('reason', '')}", verdict="pass", retry_count=retry,
                        data={"status": status, "confidence": confidence, "supporting_ids": verdict["supporting_ids"]})
        return verdict

    def _confidence(self, supporting: list[dict], checks: dict) -> str:
        def bad_rel(e):
            m = METRICS[e["metric"]]
            return abs(e["rel"] or 0) / m.min_rel
        full = [e for e in supporting if not checks[e["id"]]["small_sample"]]
        if not full:
            return "low"
        kinds = {e["contrast_type"] for e in full}
        if len(kinds) >= 2 and max(bad_rel(e) for e in full) >= 2:
            return "high"
        return "medium"

    def _block(self, verdict: dict, reasons: list[str], retry: int) -> dict:
        verdict.update(status="blocked", blocked=True, reasons=reasons)
        self.trace.emit("block", self.name, "block_claim", input_summary=verdict["hypothesis_id"],
                        output_summary="; ".join(reasons), verdict="block", retry_count=retry,
                        status="blocked", data={"reasons": reasons})
        return verdict

    # ---- V4: decoy split ---------------------------------------------------------------------------
    def decoy_split(self, demand: dict | None, spend: dict | None) -> dict[str, Any] | None:
        """Share of a revenue change explained by fewer parties (volume) vs revenue per party."""
        if not demand or not spend or demand["baseline"] in (None, 0) or spend["baseline"] is None:
            return None
        p_f, p_b, s_f, s_b = demand["value"], demand["baseline"], spend["value"], spend["baseline"]
        r_f, r_b = p_f * s_f, p_b * s_b
        change = r_f - r_b
        volume = (p_f - p_b) * s_b
        spend_part = p_f * (s_f - s_b)
        share = None
        if change < 0:
            share = max(0.0, min(1.0, volume / change)) if volume < 0 else 0.0
        out = {"revenue_focus": round(r_f, 2), "revenue_baseline": round(r_b, 2), "change": round(change, 2),
               "change_rel": round(change / r_b, 4) if r_b else None, "volume_effect": round(volume, 2),
               "spend_effect": round(spend_part, 2), "volume_share": None if share is None else round(share, 3),
               "decoy_dominant": share is not None and share >= THRESHOLDS["V4_decoy_share"],
               "evidence_ids": [demand["id"], spend["id"]]}
        self.trace.emit("verify", self.name, "V4_decoy_split", input_summary="fewer parties vs revenue per party",
                        output_summary=(f"volume explains {share:.0%} of the change" if share is not None else
                                        "revenue did not fall; no split needed") +
                        ("; decoy dominant -> downgrade service findings" if out["decoy_dominant"] else ""),
                        verdict="downgrade" if out["decoy_dominant"] else "pass", data=out)
        return out
