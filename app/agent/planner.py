"""Planner: question -> intent, slots and at most three hypotheses from the data-defined library.

The model chooses; code enforces policy: unknown ids are dropped, the cap is three, a revenue question
always carries the demand hypothesis (the Verifier's decoy rule V4 needs it), and a request to rank
individual staff is reframed to staffing conditions (SPEC §6 framing rule).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.metrics import METRICS

LIBRARY_PATH = Path(__file__).with_name("hypotheses.yaml")
MAX_HYPOTHESES = 3
INTENTS = ("explain", "compare", "probe", "abstain", "rank_individuals")
SLOT_KEYS = ("weekday", "date", "period", "service", "section", "window")
REVENUE_METRICS = ("net_revenue", "parties", "net_revenue_per_party")

SYSTEM = """You are the Planner of ServiceWhy, an agent that explains why a restaurant's service or revenue changed.
You never answer the question. You choose which hypotheses to investigate and extract time/segment slots.
Return ONE JSON object and nothing else."""

PROMPT = """Question: {question}
{context}
Data available (synthetic restaurant, latest business date {as_of}): POS tickets and items, table-service events
(seated, greeted, ordered, fired, bumped, delivered, paid, left, reset), shift rosters (servers by section with
tables assigned, bussers), plate returns, guest reviews. Nothing else exists: no menu changes, tips, prices,
marketing, weather or staff performance records.

Hypothesis library (choose at most {max_h} ids):
{library}

Metrics: {metrics}

Return JSON with exactly these keys:
{{"intent": one of {intents},
  "target_metric": a metric id or null,
  "slots": {{"weekday": "mon".."sun" or null, "date": "YYYY-MM-DD" or null,
             "period": "this_week" | "last_week" | "weekend" | null, "service": "lunch" | "dinner" | null,
             "section": "A".."D" or null, "window": "HH:MM-HH:MM" or null, "compare_previous": true | false}},
  "hypotheses": [ids],
  "missing_data": null or a short phrase naming the data the question needs but the restaurant does not record,
  "reason": one sentence}}
Rules: "abstain" when the question's cause or metric is not in the data (set missing_data, hypotheses []).
"rank_individuals" when asked to rank or blame a named or individual staff member.
"probe" for yes/no questions about one stage. "compare" for period-over-period questions (compare_previous true).
"""


def load_library(path: Path = LIBRARY_PATH) -> dict[str, dict[str, Any]]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {e["id"]: e for e in entries}


def build_prompt(question: str, library: dict, as_of: str, context: str | None = None) -> str:
    lib = "\n".join(f"- {h['id']} ({h['family']}): {h['statement']}. Keywords: {', '.join(h['keywords'])}"
                    for h in library.values())
    metrics = ", ".join(f"{m.id} ({m.label})" for m in METRICS.values())
    ctx = f"Earlier question in this conversation (resolve 'the drop' etc. against it): {context.strip()}\n" \
        if context else ""
    return PROMPT.format(question=question.strip(), context=ctx, as_of=as_of, max_h=MAX_HYPOTHESES, library=lib,
                         metrics=metrics, intents=json.dumps(list(INTENTS)))


def normalise(raw: dict[str, Any], library: dict) -> dict[str, Any]:
    """Validate the model's plan and apply policy. Returns the plan the loop will execute."""
    intent = raw.get("intent") if raw.get("intent") in INTENTS else "explain"
    target = raw.get("target_metric") if raw.get("target_metric") in METRICS else None
    slots = {k: (raw.get("slots") or {}).get(k) for k in SLOT_KEYS}
    slots["compare_previous"] = bool((raw.get("slots") or {}).get("compare_previous")) or intent == "compare"
    if slots["service"] not in ("lunch", "dinner"):
        slots["service"] = None
    if slots["section"] not in ("A", "B", "C", "D"):
        slots["section"] = None
    hyps = [h for h in dict.fromkeys(raw.get("hypotheses") or []) if h in library]
    notes = []
    if intent == "rank_individuals":
        hyps = ["H_SERVER_LOAD", "H_BUSSER"]
        slots.update(section=None)
        notes.append("Individual ranking refused; reframed to staffing conditions by section and shift.")
    if intent == "abstain":
        hyps = []
    elif target in REVENUE_METRICS and not {"H_DEMAND", "H_SPEND"} <= set(hyps):
        hyps = ["H_DEMAND", "H_SPEND"] + [h for h in hyps if h not in ("H_DEMAND", "H_SPEND")]
        notes.append("Demand and spend hypotheses kept: a revenue claim must be split into fewer parties vs "
                     "revenue per party (rule V4).")
    if intent != "abstain" and not hyps:
        intent, notes = "abstain", notes + ["No library hypothesis matches the question."]
    if len(hyps) > MAX_HYPOTHESES:
        hyps = hyps[:MAX_HYPOTHESES]
    return {"intent": intent, "target_metric": target, "slots": slots, "hypotheses": hyps,
            "missing_data": raw.get("missing_data") if intent == "abstain" else None,
            "reason": str(raw.get("reason") or ""), "policy_notes": notes}


class Planner:
    name = "Planner"
    role = "Turns the question into at most three hypotheses from the library and a query plan"

    def __init__(self, model, library: dict | None = None):
        self.model, self.library = model, library or load_library()

    def plan(self, question: str, as_of: str, context: str | None = None) -> tuple[dict[str, Any], str]:
        raw, _ = self.model.complete_json("planner", build_prompt(question, self.library, as_of, context), SYSTEM)
        return normalise(raw, self.library), raw.get("reason", "")
