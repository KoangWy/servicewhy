"""Scorecard harness: run the canned questions, join traces + World Model logs with ground truth.

  python -m app.scorecard.harness            # prints the README markdown, writes logs/scorecard.{md,json}

This module is the ONLY reader of ground truth (SPEC §4.3). Agent-side modules never import it — a
default-suite test greps them. Traces with an unknown schema version are refused.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.config import Settings, load_dotenv
from app.logging.trace import read_trace

QUESTIONS = Path(__file__).with_name("questions.yaml")
INCIDENT_HYPOTHESIS = {"I1": "H_SERVER_LOAD", "I4": "H_BUSSER"}
STAFF_ID = re.compile(r"\b(?:S[1-9]|B[12])\b")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_ground_truth(settings: Settings) -> dict:
    path = settings.data_dir / "ground_truth.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if settings.data_backend == "local":  # keyless: the same seeded run the local store serves
        from app.sim.simulator import Simulator
        return Simulator(seed=settings.seed, days=settings.sim_days).run()[1]
    raise FileNotFoundError(f"{path} missing: run `make seed` first (FULL mode)")


def _wm_evidence(logs_dir: Path, run_id: str) -> dict[str, dict]:
    path = logs_dir / f"worldmodel-{run_id}.jsonl"
    out: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec["kind"] == "evidence":
                out.setdefault(rec["id"], {}).update(rec["data"])
    return out


def covers(evidence: dict, incident: dict) -> bool:
    """Does an evidence item's query window include nights the incident was active?"""
    spec, p = evidence.get("spec") or {}, incident["params"]
    lo = incident.get("active_from", "0000-00-00")
    days = [d for d in spec.get("focus", []) if d >= lo and WEEKDAYS[date.fromisoformat(d).weekday()] in p.get("weekdays", WEEKDAYS)]
    return bool(days)


def grade(q: dict, resp: dict, events: list[dict], evidence: dict[str, dict], gt: dict) -> dict[str, Any]:
    exp, out = q["expect"], resp.get("output") or {}
    findings = out.get("findings", [])
    g: dict[str, Any] = {"id": q["id"], "kind": q["kind"], "question": q["question"], "status": resp["status"],
                         "answer_type": out.get("answer_type"), "checks": {}}
    c = g["checks"]
    c["answer_type"] = out.get("answer_type") == exp["answer_type"]
    if "incident" in exp:
        inc = next(i for i in gt["incidents"] if i["id"] == exp["incident"])
        top = findings[0] if findings else None
        named = bool(top) and all(n.lower() in top["cause_hypothesis"].lower() for n in exp.get("names", []))
        cited = [evidence.get(e["evidence_id"], {}) for e in (top or {}).get("evidence", [])]
        c["root_cause_hit"] = named and any(covers(e, inc) for e in cited)
    if exp.get("split"):
        c["split"] = bool(out.get("revenue_split")) and "fewer parties explain" in out.get("summary", "")
    if "decoy" in exp:
        top = findings[0] if findings else None
        c["decoy_rejected"] = bool(out.get("revenue_split")) and bool(top) and top.get("family") != "volume"
    if "not_cause" in exp:
        c["not_cause"] = all(f.get("library_id") != exp["not_cause"] for f in findings)
    if exp.get("no_individuals"):
        c["no_individuals"] = not STAFF_ID.search(json.dumps(out).replace("section B", ""))
    if "sources" in exp:
        srcs = " ".join(e["source"] for f in findings for e in f["evidence"])
        c["cross_source"] = all(s in srcs for s in exp["sources"])
    cited_all = [e for f in findings for e in f["evidence"]]
    g["cited"] = len(cited_all)
    g["cited_supporting"] = sum(1 for e in cited_all if e.get("supports"))
    g["item_blocks"] = sum(1 for e in events if e["event"] == "verify" and e.get("verdict") == "block")
    g["claim_blocks"] = sum(1 for e in events if e["event"] == "block" and e["action"] == "block_claim")
    g["retries"] = sum(1 for e in events if e["event"] == "retry")
    v5 = [e for e in events if e["action"] == "V5_insufficient_evidence"]
    present = {INCIDENT_HYPOTHESIS[i["id"]] for i in gt["incidents"] if i["id"] in INCIDENT_HYPOTHESIS}
    blocked_libs = {h.get("library_id") for h in _blocked_hypotheses(out)}
    g["wrongly_blocked"] = len(blocked_libs & present) if v5 else 0
    g["pass"] = all(c.values())
    return g


def _blocked_hypotheses(out: dict) -> list[dict]:
    plan_ids = (out.get("plan") or {}).get("hypotheses", [])
    stmts = {b["statement"] for b in out.get("insufficient", [])}
    from app.agent.planner import load_library
    lib = load_library()
    return [{"library_id": h} for h in plan_ids if lib[h]["statement"] in stmts]


def summarise(rows: list[dict]) -> dict[str, Any]:
    def rate(key: str) -> tuple[int, int]:
        xs = [r["checks"][key] for r in rows if key in r["checks"]]
        return sum(xs), len(xs)
    abst = [r for r in rows if r["kind"].startswith("abstain")]
    cited = sum(r["cited"] for r in rows)
    return {
        "root_cause_hit": rate("root_cause_hit"),
        "evidence_precision": (sum(r["cited_supporting"] for r in rows), cited),
        "unsupported_claims_caught": sum(r["item_blocks"] + r["claim_blocks"] for r in rows),
        "wrongly_blocked": sum(r["wrongly_blocked"] for r in rows),
        "decoy_rejection": rate("decoy_rejected"),
        "abstention_correct": (sum(r["checks"]["answer_type"] for r in abst), len(abst)),
        "retries_per_investigation": round(sum(r["retries"] for r in rows) / max(1, len(rows)), 2),
        "questions_passed": (sum(r["pass"] for r in rows), len(rows)),
    }


def markdown(summary: dict, rows: list[dict], meta: dict) -> str:
    f = lambda t: f"{t[0]}/{t[1]}" + (f" ({100 * t[0] / t[1]:.0f}%)" if t[1] else "")  # noqa: E731
    lines = [f"Scorecard - {meta['date']} - seed {meta['seed']} - data: {meta['data']} - model: {meta['model']}", "",
             "| Metric | Result |", "|---|---|",
             f"| Root-cause hit rate (top finding names the injected condition and cites its window) | {f(summary['root_cause_hit'])} |",
             f"| Evidence precision (cited items that support their claim) | {f(summary['evidence_precision'])} |",
             f"| Verifier: unsupported claims caught / wrongly blocked | {summary['unsupported_claims_caught']} / {summary['wrongly_blocked']} |",
             f"| Decoy rejection rate | {f(summary['decoy_rejection'])} |",
             f"| Abstention correctness | {f(summary['abstention_correct'])} |",
             f"| Retries per investigation | {summary['retries_per_investigation']} |",
             f"| Questions passing every check | {f(summary['questions_passed'])} |", "",
             "| # | Kind | Question | Answer | Checks |", "|---|---|---|---|---|"]
    for r in rows:
        checks = ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in r["checks"].items())
        lines.append(f"| {r['id']} | {r['kind']} | {r['question']} | {r['answer_type']} | {checks} |")
    return "\n".join(lines)


def run(settings: Settings, orchestrator=None) -> dict[str, Any]:
    if orchestrator is None:
        from app.runtime import orchestrator as make
        orchestrator = make(settings)
    gt = load_ground_truth(settings)
    rows, mode = [], {}
    for q in load_questions():
        resp = orchestrator.run(q["question"], run_id=f"score-{q['id'].lower()}", context=q.get("context"))
        events = read_trace(settings.logs_dir / f"trace-{resp['run_id']}.jsonl")
        rows.append(grade(q, resp, events, _wm_evidence(settings.logs_dir, resp["run_id"]), gt))
        mode = (resp.get("output") or {}).get("mode") or mode
    summary = summarise(rows)
    meta = {"date": time.strftime("%Y-%m-%d"), "seed": settings.seed, "data": mode.get("data"), "model": mode.get("model")}
    md = markdown(summary, rows, meta)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "scorecard.md").write_text(md + "\n", encoding="utf-8", newline="\n")
    (settings.logs_dir / "scorecard.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows},
                                                                 indent=1), encoding="utf-8", newline="\n")
    return {"summary": summary, "rows": rows, "markdown": md, "meta": meta}


def main() -> int:
    load_dotenv()
    res = run(Settings.from_env())
    try:
        print(res["markdown"])
    except UnicodeEncodeError:
        print(res["markdown"].encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
