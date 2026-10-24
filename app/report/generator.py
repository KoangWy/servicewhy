"""Period report = a batch run of the same investigation core (SPEC §6).

Two investigations over the period vs the previous period: the money side (demand, spend, reviews,
with the V4 revenue split) and the floor side (server load, bussers, kitchen). The report keeps the
top 3-5 verified findings, one summary paragraph and a data-provenance appendix.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, timedelta
from typing import Any

from app.agent.verifier import THRESHOLDS

MAX_FINDINGS = 5
BATCH = [
    ("How did revenue, guest counts and reviews change this period compared with the previous one?",
     {"intent": "compare", "target_metric": "net_revenue", "hypotheses": ["H_DEMAND", "H_SPEND", "H_REVIEWS"]}),
    ("Which service conditions slowed the floor this period?",
     {"intent": "explain", "target_metric": None, "hypotheses": ["H_SERVER_LOAD", "H_BUSSER", "H_KITCHEN"]}),
]


def default_period(as_of: str) -> dict[str, str]:
    end = date.fromisoformat(as_of)
    end -= timedelta(days=(end.weekday() + 1) % 7)  # latest Sunday on or before as_of
    return {"start": (end - timedelta(days=6)).isoformat(), "end": end.isoformat()}


def generate(orchestrator, period: dict[str, str], *, report_id: str | None = None) -> dict[str, Any]:
    report_id = report_id or f"rep-{uuid.uuid4().hex[:8]}"
    t0 = time.time()
    runs = []
    for question, plan in BATCH:
        slots = {"start": period["start"], "end": period["end"], "compare_previous": True}
        override = {**plan, "slots": slots, "missing_data": None, "reason": "period report batch",
                    "policy_notes": ["Report batch run: hypotheses fixed by the report template."]}
        runs.append(orchestrator.run(question, run_id=f"{report_id}-{len(runs) + 1}", plan_override=override))
    ok = [r for r in runs if r["status"] == "success"]
    order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted((dict(f, run_id=r["run_id"]) for r in ok for f in r["output"]["findings"]),
                      key=lambda f: (order[f["confidence"]], f["family"] == "volume"))[:MAX_FINDINGS]
    summary = " ".join(r["output"]["summary"] for r in ok) or "The report could not be generated; see errors."
    first = ok[0]["output"] if ok else {}
    return {
        "report_id": report_id, "period": period, "status": "success" if ok else "error",
        "summary": summary, "findings": findings,
        "revenue_split": first.get("revenue_split"),
        "not_causes": [n for r in ok for n in r["output"]["not_causes"]],
        "insufficient": [n for r in ok for n in r["output"]["insufficient"]],
        "provenance": {
            "data": "Fully synthetic restaurant data from a seeded simulator (no real guests or staff).",
            "channel": first.get("mode", {}).get("data"), "model": first.get("mode", {}).get("model"),
            "data_as_of": first.get("data_as_of"),
            "stores": {"PostgreSQL": ["pos_tickets", "ticket_items", "table_events"],
                       "Parquet on MinIO": ["shifts", "plate_returns", "reviews"]},
            "comparison": "period vs the previous period of equal length (SPEC D11)",
            "thresholds": THRESHOLDS,
            "runs": [{"run_id": r["run_id"], "question": r["question"], "status": r["status"],
                      "trace": r.get("log_file")} for r in runs],
        },
        "errors": [r["error"] for r in runs if r["status"] != "success"],
        "execution_time_seconds": round(time.time() - t0, 2),
        "_runs": runs,  # full run responses; the API registers them and drops this key
    }
