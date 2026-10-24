"""Writer: findings in the SPEC §6 contract and the final answer, with no invented numbers.

Finding fields come from the library templates filled with what the evidence discovered (worst
section, tables-per-server bucket, bussers on duty, time window, complaint theme). The model writes
the answer paragraph; a number guard rejects any figure that is not in the cited evidence and falls
back to a deterministic answer (visible in the trace).
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.agent.investigator import fmt
from app.agent.verifier import downgrade
from app.metrics import METRICS

SYSTEM = """You are the Writer of ServiceWhy. Write the manager-facing answer from verified findings only.
Name staffing or process conditions (section, shift, time window), never individual people. Every number you
write must come from the input, and cite the evidence id in square brackets after it. Keep it under 120 words.
Return ONE JSON object: {"answer": "..."}."""

DIM_KEYS = {"section": "section", "tables_per_server": "tables_per_server", "bussers_on": "bussers_on",
            "window": "window", "theme": "theme"}
# wording used in actions/uncertainty when the evidence did not pin a value down (never in the cause)
DEFAULTS = {"section": "the affected section", "tables_per_server": "too many", "bussers_on": "one",
            "window": "the late window", "theme": "slow service"}
_NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:\.\d+)?")


class _Blank(dict):
    def __missing__(self, key):
        raise KeyError(key)


def fill(template: str | list[str], values: dict[str, Any], fallback: str) -> str:
    """First template whose placeholders the evidence can fill; never guess a value."""
    for t in ([template] if isinstance(template, str) else template):
        try:
            return " ".join(t.format_map(_Blank(values)).split())
        except KeyError:
            continue
    return fallback


def _signed(v: float, unit: str) -> str:
    s = fmt(abs(v), unit)
    return ("+" if v >= 0 else "-") + s


class Writer:
    name = "Writer"
    role = "Writes findings and the answer; every number cites a verified evidence item"

    def __init__(self, model, ingest, context, trace):
        self.model, self.ingest, self.context, self.trace = model, ingest, context, trace

    def finding(self, hyp: dict, verdict: dict, evidence: list[dict], scope_label: str,
                decoy: dict | None) -> dict[str, Any]:
        passed = [e for e in evidence if e["id"] in verdict["passed_ids"]]
        supporting = [e for e in passed if e["id"] in verdict.get("supporting_ids", [])]
        found = {"focus": scope_label}
        for e in passed:
            dim = e["spec"].get("dim")
            if dim in DIM_KEYS and e["group"] is not None and (e["supports"] or e["descriptive"]):
                found.setdefault(DIM_KEYS[dim], e["group"])
        primary = supporting[0]  # plans are ordered: the first supporting contrast is the headline
        m = METRICS[primary["metric"]]
        confidence = verdict["confidence"]
        if decoy and decoy["decoy_dominant"] and hyp["family"] != "volume":
            confidence = downgrade(confidence)
        statement = f"{hyp['statement']} ({scope_label})"
        cited = sorted(supporting, key=lambda e: -abs(e["rel"] or 0)) + [e for e in passed if e not in supporting]
        f = {
            "cause_hypothesis": fill(hyp["cause"], found, statement),
            "evidence": [{"evidence_id": e["id"], "source": e["source"], "query": e["query"], "metric": e["metric"],
                          "contrast": e["contrast"], "group": e["group"], "value": _r(e["value"]),
                          "baseline": _r(e["baseline"]), "n": e["n"], "n_baseline": e["n_baseline"],
                          "supports": e["supports"]} for e in cited],
            "confidence": confidence,
            "effect_size": {"metric": m.id, "delta": _signed(primary["delta"], m.unit),
                            "relative": f"{100 * primary['rel']:+.0f}%" if primary["rel"] is not None else None,
                            "evidence_id": primary["id"]},
            "uncertainty": fill(hyp.get("uncertainty", ""), {**DEFAULTS, **found}, hyp.get("uncertainty", "")),
            "recommended_action": fill(hyp["action"], {**DEFAULTS, **found}, hyp["action"]),
            "status": "proposed",
            "hypothesis_id": hyp["wm_id"], "library_id": hyp["id"], "family": hyp["family"],
        }
        if decoy and hyp["family"] == "volume" and decoy.get("volume_share") is not None:
            f["decoy_share"] = decoy["volume_share"]
        fid = self.ingest.ingest_finding(hyp["wm_id"], text=f["cause_hypothesis"],
                                         evidence_ids=[e["evidence_id"] for e in f["evidence"]], agent_id="writer",
                                         **{k: v for k, v in f.items() if k not in ("evidence", "hypothesis_id")})
        f = {"id": fid, **f}
        self.trace.emit("answer", self.name, "write_finding", input_summary=hyp["wm_id"],
                        output_summary=f"{fid}: {f['cause_hypothesis']} [{confidence}]",
                        data={"finding_id": fid, "confidence": confidence, "evidence_ids": [e["evidence_id"] for e in f["evidence"]]})
        return f

    # ---- the answer --------------------------------------------------------------------------------
    def answer(self, question: str, plan: dict, findings: list[dict], rejected: list[dict], blocked: list[dict],
               decoy: dict | None) -> dict[str, Any]:
        if plan["intent"] == "abstain":
            missing = plan.get("missing_data") or "the data this question needs"
            text = (f"Insufficient evidence. The restaurant's data does not record {missing}, so ServiceWhy "
                    f"will not guess at this cause.")
            return {"answer_type": "insufficient_evidence", "summary": text}
        if not findings and not rejected:
            reasons = "; ".join(r for b in blocked for r in b.get("reasons", []))[:300]
            return {"answer_type": "insufficient_evidence",
                    "summary": f"Insufficient evidence. Every hypothesis was blocked by the verifier after retries ({reasons})."}
        payload = {"question": question, "intent": plan["intent"], "policy_notes": plan.get("policy_notes", []),
                   "findings": [{k: f[k] for k in ("id", "cause_hypothesis", "confidence", "effect_size", "recommended_action")}
                                | {"evidence": [{k: e[k] for k in ("evidence_id", "metric", "group", "value", "baseline", "n")}
                                                for e in f["evidence"][:3]]} for f in findings],
                   "not_causes": [{"statement": r["statement"], "evidence": r["evidence"]} for r in rejected],
                   "blocked": [{"statement": b["statement"], "reasons": b.get("reasons", [])} for b in blocked],
                   "revenue_split": decoy}
        fallback = self._template(plan, findings, rejected, blocked, decoy)
        try:
            out, _ = self.model.complete_json("writer", "Write the answer.\n<<INPUT>>\n" +
                                              json.dumps(payload, sort_keys=True, default=str) + "\n<<END>>", SYSTEM)
            text = str(out.get("answer", "")).strip()
        except (ValueError, KeyError) as e:
            text, bad = "", [f"unparseable writer output: {e}"]
        else:
            bad = self.unsupported_numbers(text, question, payload) if text else []
        if not text and not bad:
            self.trace.emit("answer", self.name, "template_answer", output_summary="model returned no answer text; "
                            "using the deterministic template")
            text = fallback
        elif bad:
            self.trace.emit("block", self.name, "number_guard", input_summary="model answer",
                            output_summary=f"rejected model answer: numbers not in evidence {bad[:5]}; using template",
                            verdict="block", status="blocked", data={"unsupported": bad[:20]})
            text = fallback
        kind = "reframed" if plan["intent"] == "rank_individuals" else "answer"
        return {"answer_type": kind, "summary": text}

    @staticmethod
    def unsupported_numbers(text: str, question: str, payload: dict) -> list[str]:
        allowed: set[str] = set(_NUM.findall(question))
        blob = json.dumps(payload, default=str)
        for raw in re.findall(r"-?\d+(?:\.\d+)?", blob):
            v = abs(float(raw))
            for x in (v, 100 * v):
                for nd in (0, 1, 2):
                    allowed.add(f"{round(x, nd):.{nd}f}")
                    allowed.add(f"{round(x, nd):,.{nd}f}")
        cleaned = re.sub(r"\b(?:evd|fnd|hyp)_[0-9a-f]+\b", " ", text)
        cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", cleaned)
        return [n for n in _NUM.findall(cleaned) if n not in allowed and n.rstrip(".") not in allowed]

    def _template(self, plan, findings, rejected, blocked, decoy) -> str:
        parts = []
        if plan["intent"] == "rank_individuals":
            parts.append("ServiceWhy does not rank individual staff. The staffing conditions behind slow service were:")
        if decoy and decoy.get("volume_share") is not None:
            parts.append(f"Revenue changed {100 * decoy['change_rel']:+.0f}% vs the baseline: fewer parties explain "
                         f"{100 * decoy['volume_share']:.0f}% of it and lower revenue per party "
                         f"{100 * (1 - decoy['volume_share']):.0f}% [{decoy['evidence_ids'][0]}, {decoy['evidence_ids'][1]}].")
        for f in findings:
            e = f["effect_size"]
            parts.append(f"{f['cause_hypothesis']} ({e['delta']}, {e['relative']}) [{e['evidence_id']}] "
                         f"— {f['confidence']} confidence. Action: {f['recommended_action']}.")
        for r in rejected:
            ev = r["evidence"][0] if r["evidence"] else None
            tail = f" [{ev['evidence_id']}]" if ev else ""
            nums = (f" ({fmt(ev['value'], ev['unit'])} vs {fmt(ev['baseline'], ev['unit'])}, n={ev['n']})"
                    if ev and ev.get("baseline") is not None else "")
            lead = "No. " if plan["intent"] == "probe" else "Not a cause: "
            parts.append(f"{lead}{r['negative']}{nums}{tail}.")
        if blocked:
            parts.append("Blocked for insufficient evidence: " + "; ".join(b["statement"] for b in blocked) + ".")
        return " ".join(parts)


def _r(v: Any) -> Any:
    return round(v, 3) if isinstance(v, float) else v
