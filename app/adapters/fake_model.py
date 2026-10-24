"""Deterministic offline stand-in for the model (MODEL_MODE=fake): tests and keyless development only.

It reads the same prompts the real model gets and answers in the same JSON shapes, using keyword
rules for the Planner, a sample-size/contrast rule for the Verifier and a plain template for the
Writer. It is never used in FULL mode; recorded cassettes replace it once real runs exist.
"""
from __future__ import annotations

import json
import re

WEEKDAYS = {"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu", "friday": "fri",
            "saturday": "sat", "sunday": "sun"}


def _payload(prompt: str) -> dict:
    m = re.search(r"<<INPUT>>\n(.*)\n<<END>>", prompt, re.S)
    return json.loads(m.group(1)) if m else {}


def plan(question: str, context: str | None = None) -> dict:
    q = question.lower()
    if context and re.search(r"\b(the|this) (drop|decline|change)\b", q):  # follow-up: inherit slots and target
        q = q + " " + context.lower()
    slots = {"weekday": None, "date": None, "period": None, "service": None, "section": None, "window": None,
             "compare_previous": False}
    for name, short in WEEKDAYS.items():
        if name in q:
            slots["weekday"] = short
    if re.search(r"\b(dinner|night|nights|evening)\b", q):
        slots["service"] = "dinner"
    if "lunch" in q:
        slots["service"] = "lunch"
    sec = re.search(r"\bsection ([a-d])\b", q)
    if sec:
        slots["section"] = sec.group(1).upper()
    if "weekend" in q:
        slots["period"] = "weekend"
    if "this week" in q:
        slots["period"] = "this_week"
    out = {"intent": "explain", "target_metric": None, "slots": slots, "hypotheses": [], "missing_data": None,
           "reason": "keyword plan (offline fake model)"}
    if re.search(r"\b(worst|best|laziest|slowest) (server|waiter|staff|busser)\b|\bwho is\b", q):
        out.update(intent="rank_individuals", hypotheses=["H_SERVER_LOAD", "H_BUSSER"])
    elif "menu" in q:
        out.update(intent="abstain", missing_data="menu changes")
    elif re.search(r"\btips?\b", q):
        out.update(intent="abstain", missing_data="tips")
    elif "compare" in q or " vs " in q or "versus" in q:
        slots["compare_previous"] = True
        out.update(intent="compare", target_metric="net_revenue", hypotheses=["H_DEMAND", "H_SPEND", "H_SERVER_LOAD"])
    elif "review" in q:
        out.update(target_metric="low_rating_share", hypotheses=["H_REVIEWS", "H_SERVER_LOAD", "H_BUSSER"])
    elif "kitchen" in q:
        out.update(intent="probe", target_metric="kitchen_min", hypotheses=["H_KITCHEN"])
    elif re.search(r"\b(reset|clear|turnover)\b", q):
        out.update(target_metric="reset_min", hypotheses=["H_BUSSER"])
        if "late" in q:
            slots["service"] = "dinner"
    elif "greet" in q:
        out.update(target_metric="greet_min", hypotheses=["H_SERVER_LOAD"])
    elif re.search(r"revenue|sales|fewer customers|customers|covers", q):
        out.update(target_metric="net_revenue", hypotheses=["H_DEMAND", "H_SPEND", "H_SERVER_LOAD"])
    else:
        out.update(intent="abstain", missing_data="data matching this question")
    return out


def verify(payload: dict) -> dict:
    ev = [e for e in payload.get("evidence", []) if not e.get("descriptive")]
    if payload.get("proposed_status") == "supported":
        support = [e for e in ev if e.get("supports_claim")]
        strong = [e for e in support if not e.get("small_sample")]
        kinds = {e.get("contrast_type") for e in support}
        if strong:
            return {"verdict": "pass", "reason": f"{len(strong)} adequately sized contrast(s) support the claim"}
        if len(kinds) >= 2:
            return {"verdict": "pass", "reason": f"small samples, but {len(kinds)} independent contrast types agree"}
        return {"verdict": "block", "reason": "one small-sample contrast is not enough; widen the sample"}
    return {"verdict": "pass", "reason": "contrasts show no meaningful change, so the hypothesis is not a cause"}


def respond(role: str, system_prompt: str | None, prompt: str) -> str:
    if role == "planner":
        q = re.search(r"^Question: (.*)$", prompt, re.M)
        c = re.search(r"^Earlier question in this conversation \(.*?\): (.*)$", prompt, re.M)
        return json.dumps(plan(q.group(1) if q else "", c.group(1) if c else None))
    if role == "verifier":
        return json.dumps(verify(_payload(prompt)))
    if role == "writer":
        if "<<INPUT>>" not in prompt:  # Meterless gate style prompt: cite the first evidence id
            ids = re.findall(r"evd_[0-9a-f]{12}", prompt)
            return f"Finding supported by [{ids[0]}]." if ids else "No evidence supplied."
        return json.dumps({"answer": ""})  # empty -> the Writer's deterministic template
    raise ValueError(f"fake model has no rule for role {role!r}")
