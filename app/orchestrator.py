"""Orchestrator: one investigation = Planner -> Investigator -> Verifier (block / retry) -> Writer.

Bounded by construction: at most 3 hypotheses, at most 2 verifier retries per hypothesis (each retry
widens the sample to more of the same nights), and a hard cap of 12 investigate+verify steps per run.
Every step lands in the run trace; every hypothesis, evidence item and finding lands in the World Model.
"""
from __future__ import annotations

import os
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

from app.adapters.model import CassetteMiss, ModelAdapter, ModelBudgetExceeded, ModelProviderError
from app.model_config import ModelNotConfigured
from app.agent.investigator import Investigator
from app.agent.planner import REVENUE_METRICS, Planner, load_library
from app.agent.scope import Scope, resolve, widen
from app.agent.verifier import THRESHOLDS, Verifier
from app.agent.writer import Writer, fill
from app.config import Settings
from app.logging.trace import Trace
from app.worldmodel.context_builder import ContextBuilderService
from app.worldmodel.ingest import IngestPipelineService
from app.worldmodel.store import WorldStoreService

MAX_STEPS = 12
AGENTS = [{"name": c.name, "role": c.role} for c in (Planner, Investigator, Verifier, Writer)]


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:10]}"


class Orchestrator:
    def __init__(self, settings: Settings, data_factory: Callable[[], Any],
                 model_factory: Callable[[str], ModelAdapter] | None = None):
        self.settings, self.data_factory = settings, data_factory
        self.model_factory = model_factory or (lambda session: ModelAdapter(
            settings.model_mode, session_id=session, cassette_dir=settings.cassette_dir,
            max_calls=int(os.environ.get("MODEL_MAX_CALLS", "40"))))
        self.library = load_library()

    def run(self, question: str, *, run_id: str | None = None, plan_override: dict | None = None,
            parent_finding: str | None = None, context: str | None = None) -> dict[str, Any]:
        run_id = run_id or new_run_id()
        t0 = time.time()
        trace = Trace(run_id, self.settings.logs_dir)
        try:
            out = self._run(question, run_id, trace, plan_override, parent_finding, context)
            status = "success"
        except Exception as e:  # structured error, never a silent crash (Technical Execution Guide §2)
            kind = type(e).__name__
            recoverable = isinstance(e, (CassetteMiss, ModelBudgetExceeded, TimeoutError, ConnectionError, ModelProviderError,
                                         ModelNotConfigured))
            trace.emit("run_end", "Orchestrator", "error", output_summary=f"{kind}: {e}", status="error",
                       data={"traceback": traceback.format_exc()[-2000:],
                             "model_calls": getattr(trace, "model_call_log", [])})
            return {"run_id": run_id, "status": "error", "question": question,
                    "error": {"type": kind, "message": str(e)[:500], "recoverable": recoverable},
                    "trace_id": f"trace-{run_id}", "log_file": _rel(trace.path),
                    "execution_time_seconds": round(time.time() - t0, 2)}
        elapsed = round(time.time() - t0, 2)
        trace.emit("run_end", "Orchestrator", "complete", output_summary=f"{status} in {elapsed}s",
                   data={"execution_time_seconds": elapsed, "model_calls": getattr(trace, "model_call_log", [])})
        return {"run_id": run_id, "status": status, "question": question, "output": out, "agents": AGENTS,
                "trace_id": f"trace-{run_id}", "log_file": _rel(trace.path), "execution_time_seconds": elapsed}

    def _run(self, question: str, run_id: str, trace: Trace, plan_override: dict | None,
             parent_finding: str | None, context: str | None) -> dict[str, Any]:
        s = self.settings
        session = str(uuid.uuid5(uuid.NAMESPACE_URL, run_id))  # x-opencode-session: one per investigation
        model = self.model_factory(session)
        trace.model_call_log = model.call_log  # read by run_end, including after a failed run
        data = self.data_factory()
        wm_path = s.logs_dir / f"worldmodel-{run_id}.jsonl"
        store = WorldStoreService(wm_path, on_mutation=lambda rec: trace.emit(
            "wm_mutation", rec["agent_id"].capitalize(), f"put_{rec['kind']}", output_summary=rec["id"],
            data={"id": rec["id"], "kind": rec["kind"], "keys": sorted(rec["data"])}))
        ingest, builder = IngestPipelineService(store, run_id=run_id), ContextBuilderService(store)
        inv = Investigator(data, pg=s.pg_source, fs=s.fs_database, trace=trace, ingest=ingest)
        verifier, writer = Verifier(inv, model, builder, trace), Writer(model, ingest, builder, trace)
        trace.emit("run_start", "Orchestrator", "start", input_summary=question,
                   data={"question": question, "data_channel": inv.channel, "model_mode": model.mode,
                         "model": model.model_id, "model_provider": model.provider, "model_id": model.model_id,
                         "parent_finding": parent_finding, "context": context,
                         "thresholds": THRESHOLDS})
        first, as_of = inv.as_of()

        plan = plan_override or Planner(model, self.library).plan(question, as_of, context)[0]
        trace.emit("plan", "Planner", "plan", input_summary=question,
                   output_summary=f"intent={plan['intent']} hypotheses={plan['hypotheses']} slots="
                                  f"{ {k: v for k, v in plan['slots'].items() if v} }",
                   data={k: plan[k] for k in ("intent", "target_metric", "slots", "hypotheses", "missing_data",
                                              "policy_notes")})
        hyps = []
        for hid in plan["hypotheses"]:
            h = dict(self.library[hid])
            h["wm_id"] = ingest.ingest_hypothesis(h["statement"], agent_id="planner", library_id=hid,
                                                  family=h["family"], plan=h["plans"], question=question)
            trace.emit("plan", "Planner", "propose_hypothesis", input_summary=hid,
                       output_summary=f"{h['wm_id']}: {h['statement']} - {len(h['plans'])} query plans",
                       data={"hypothesis_id": h["wm_id"], "library_id": hid, "plans": h["plans"]})
            hyps.append(h)

        steps, results = 0, []
        for h in hyps:
            scope: Scope | None = resolve(plan["slots"], as_of, first, 0)
            verdict, evidence = None, []
            for attempt in range(THRESHOLDS["V5_max_retries"] + 1):
                if steps >= MAX_STEPS:
                    verdict = {"status": "blocked", "blocked": True, "reasons": [f"step cap {MAX_STEPS} reached"]}
                    break
                steps += 1
                evidence = inv.investigate(h, scope, retry=attempt)
                verdict = verifier.verify(h, evidence, retry=attempt)
                if not verdict["blocked"]:
                    break
                nxt = widen(scope, first) if attempt < THRESHOLDS["V5_max_retries"] else None
                if nxt is None:
                    break
                trace.emit("retry", "Orchestrator", "widen_and_retry", input_summary=h["wm_id"],
                           output_summary=f"retry {attempt + 1}: {scope.label} -> {nxt.label}",
                           retry_count=attempt + 1, data={"from": scope.to_dict(), "to": nxt.to_dict(),
                                                          "reasons": verdict.get("reasons", [])})
                scope = nxt
            if verdict["blocked"]:
                trace.emit("block", "Verifier", "V5_insufficient_evidence", input_summary=h["wm_id"],
                           output_summary=f"insufficient evidence for '{h['statement']}' after retries",
                           verdict="block", status="blocked", retry_count=attempt,
                           data={"reasons": verdict.get("reasons", [])})
            ingest.set_status(h["wm_id"], verdict["status"], agent_id="verifier",
                              reason="; ".join(verdict.get("reasons", [])) or verdict.get("model_reason", ""))
            results.append({"hyp": h, "verdict": verdict, "evidence": evidence, "scope": scope})

        decoy = None
        if plan.get("target_metric") in REVENUE_METRICS:
            decoy = self._decoy(results, inv, verifier)
        findings = [writer.finding(r["hyp"], r["verdict"], r["evidence"], r["scope"].label, decoy,
                                   focus_plain=r["scope"].label_without_section, section=r["scope"].section)
                    for r in results if r["verdict"]["status"] == "supported"]
        order = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: (order[f["confidence"]], f["family"] == "volume"))
        rejected = [{"statement": r["hyp"]["statement"], "hypothesis_id": r["hyp"]["wm_id"], "family": r["hyp"]["family"],
                     "negative": fill(r["hyp"].get("negative", r["hyp"]["statement"]), {"focus": r["scope"].label},
                                      r["hyp"]["statement"]),
                     "evidence": [{"evidence_id": e["id"], "metric": e["metric"], "value": e["value"],
                                   "baseline": e["baseline"], "n": e["n"], "unit": e["unit"]}
                                  for e in r["evidence"] if e["id"] in r["verdict"]["passed_ids"]]}
                    for r in results if r["verdict"]["status"] == "rejected"]
        blocked = [{"statement": r["hyp"]["statement"], "hypothesis_id": r["hyp"]["wm_id"],
                    "reasons": r["verdict"].get("reasons", [])} for r in results if r["verdict"]["status"] == "blocked"]
        ans = writer.answer(question, plan, findings, rejected, blocked, decoy)
        trace.emit("answer", "Writer", "final_answer", output_summary=ans["summary"],
                   data={"answer_type": ans["answer_type"], "finding_ids": [f["id"] for f in findings]})
        return {**ans, "findings": findings, "recommendations": [f["recommended_action"] for f in findings],
                "not_causes": rejected, "insufficient": blocked, "revenue_split": decoy,
                "plan": {k: plan[k] for k in ("intent", "target_metric", "slots", "hypotheses", "policy_notes",
                                              "missing_data")},
                "scopes": {r["hyp"]["id"]: r["scope"].to_dict() for r in results},
                "steps": steps, "data_as_of": as_of,
                "mode": {"sample_mode": False, "data": inv.channel, "model": model.model_id,
                         "model_mode": model.mode, "model_calls": model.calls,
                         "model_provider": model.provider, "model_id": model.model_id,
                         "models_used": _models_used(model.call_log)},
                "artifacts": [_rel(trace.path), _rel(wm_path)], "parent_finding": parent_finding}

    def _decoy(self, results: list[dict], inv: Investigator, verifier: Verifier) -> dict | None:
        """V4 needs demand and spend measured on the same nights; re-measure spend if a retry moved it."""
        by = {r["hyp"]["id"]: r for r in results}
        pick = lambda r, metric: next((e for e in r["evidence"] if e["metric"] == metric  # noqa: E731
                                       and e["spec"]["contrast"] == "compare"
                                       and e["id"] in r["verdict"].get("passed_ids", [])), None)
        d = by.get("H_DEMAND") and pick(by["H_DEMAND"], "parties")
        sp = by.get("H_SPEND")
        s_ev = sp and pick(sp, "net_revenue_per_party")
        if d and sp and (not s_ev or s_ev["spec"]["focus"] != d["spec"]["focus"]):
            s_ev = inv.run_plan(sp["hyp"]["wm_id"], {"metric": "net_revenue_per_party", "contrast": "compare"},
                                by["H_DEMAND"]["scope"])
            if verifier.check_item(s_ev, retry=0)["blocked"]:
                s_ev = None
        return verifier.decoy_split(d, s_ev)


def _models_used(call_log: list[dict]) -> dict[str, int]:
    """How many requests each model really answered (Nightshift reports the routed model per request)."""
    used: dict[str, int] = {}
    for c in call_log:
        if c.get("ok") and c.get("routed_model"):
            used[c["routed_model"]] = used.get(c["routed_model"], 0) + 1
    return used


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path.cwd().resolve())).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")
