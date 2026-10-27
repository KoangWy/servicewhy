"""REST surface (SPEC §8). The UI and judges use the same endpoints and the same JSON contracts."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.schemas import DecisionRequest, DrilldownRequest, ReportRequest, RunRequest
from app.logging.trace import read_trace
from app.report import generator
from app.sample import SampleMiss

router = APIRouter()
RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # run ids end up in file names


def _state(request: Request):
    return request.app.state.svc


def _error(status: int, kind: str, message: str, *, recoverable: bool = True, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "error": {
        "type": kind, "message": message, "recoverable": recoverable, **extra}})


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    svc = _state(request)
    if svc.settings.sample_mode:
        zetaris = "sample"
    elif svc.settings.data_backend == "local":
        zetaris = "local"
    else:
        try:
            svc.data().query("SELECT 1 AS ok", limit=1)
            zetaris = "up"
        except Exception:
            zetaris = "down"
    model = "sample-replay" if svc.settings.sample_mode else f"{svc.settings.model_mode}"
    return {"status": "ok", "zetaris": zetaris, "model": model, "sample_mode": svc.settings.sample_mode,
            "sample_questions": svc.sample.questions if svc.settings.sample_mode else None}


@router.post("/run")
def run(body: RunRequest, request: Request):
    svc = _state(request)
    question = body.input.query
    if body.run_id is not None and not RUN_ID.match(body.run_id):
        return _error(422, "InvalidRunId", "run_id must match [A-Za-z0-9._-] and be 1-64 characters long")
    if svc.settings.sample_mode or body.options.sample_mode:
        t0 = time.time()
        try:
            resp = svc.sample.run(question)
        except SampleMiss:
            return _error(404, "SampleModeMiss", "SAMPLE_MODE serves recorded runs only; ask one of the recorded "
                          "questions or run in FULL mode.", available_questions=svc.sample.questions)
        resp["execution_time_seconds_replay"] = round(time.time() - t0, 3)
        svc.registry.add_run(resp)
        return resp
    resp = svc.orchestrator.run(question, run_id=body.run_id, context=body.input.context)
    svc.registry.add_run(resp)
    return resp if resp["status"] == "success" else JSONResponse(status_code=502, content=resp)


@router.post("/reports")
def create_report(request: Request, body: ReportRequest | None = None):
    svc = _state(request)
    if svc.settings.sample_mode:
        rep = svc.sample.report()
        if rep is None:
            return _error(404, "SampleModeMiss", "no recorded report in the sample bundle")
    else:
        if not svc.activity.begin_report():  # one generation at a time (StrictMode / a reload must not start two)
            return JSONResponse(status_code=409, content={
                "status": "error", "report_job": svc.activity.report_job(),
                "error": {"type": "ReportInProgress", "message": "a report is already being generated",
                          "recoverable": True}})
        try:
            if body and body.period:
                period = body.period.model_dump()
            else:
                rows = svc.data().query(f"SELECT MAX(business_date) AS d FROM {svc.settings.pg_source}.pos_tickets",
                                        limit=1)
                period = generator.default_period(str(rows[0]["d"])[:10])
            rep = generator.generate(svc.orchestrator, period)
        finally:
            svc.activity.end_report()
        for r in rep.pop("_runs"):
            svc.registry.add_run(r)
    svc.registry.add_report(rep)
    return {"report_id": rep["report_id"], "status": rep["status"], "period": rep["period"]}


@router.get("/reports")
def list_reports(request: Request) -> list[dict[str, Any]]:
    return [{"report_id": r["report_id"], "period": r["period"], "status": r["status"]}
            for r in _state(request).registry.reports.values()]


@router.get("/reports/{report_id}")
def get_report(report_id: str, request: Request):
    rep = _state(request).registry.reports.get(report_id)
    if rep is None:
        raise HTTPException(404, f"unknown report {report_id}")
    return rep


@router.get("/findings/{finding_id}")
def get_finding(finding_id: str, request: Request):
    reg = _state(request).registry
    f = reg.findings.get(finding_id)
    if f is None:
        raise HTTPException(404, f"unknown finding {finding_id}")
    return {**f, "run_id": reg.finding_run.get(finding_id)}


@router.post("/findings/{finding_id}/drilldown")
def drilldown(finding_id: str, request: Request, body: DrilldownRequest | None = None):
    svc = _state(request)
    f = svc.registry.findings.get(finding_id)
    if f is None:
        raise HTTPException(404, f"unknown finding {finding_id}")
    if svc.settings.sample_mode:
        resp = svc.sample.drilldown(finding_id)
        if resp is None:
            return _error(404, "SampleModeMiss", "no recorded drill-down for this finding in the sample bundle")
    else:
        question = (body.question if body and body.question else None) or f"Why: {f['cause_hypothesis']}?"
        parent = svc.registry.runs.get(svc.registry.finding_run.get(finding_id, ""), {})
        slots = ((parent.get("output") or {}).get("plan") or {}).get("slots") or {}
        override = {"intent": "explain", "target_metric": f["effect_size"]["metric"], "slots": slots,
                    "hypotheses": [f["library_id"]], "missing_data": None, "reason": "drill-down on one finding",
                    "policy_notes": [f"Drill-down on {finding_id}: same hypothesis, fresh queries."]}
        resp = svc.orchestrator.run(question, plan_override=override, parent_finding=finding_id,
                                    kind="drilldown")
    svc.registry.add_run(resp)
    return {"parent_finding": finding_id, "run": resp}


def _decide(finding_id: str, decision: str, request: Request, body: DecisionRequest | None):
    reg = _state(request).registry
    if finding_id not in reg.findings:
        raise HTTPException(404, f"unknown finding {finding_id}")
    body = body or DecisionRequest()
    return reg.decide(finding_id, decision, role=body.role, note=body.note)


@router.post("/findings/{finding_id}/approve")
def approve(finding_id: str, request: Request, body: DecisionRequest | None = None):
    return _decide(finding_id, "approve", request, body)


@router.post("/findings/{finding_id}/reject")
def reject(finding_id: str, request: Request, body: DecisionRequest | None = None):
    return _decide(finding_id, "reject", request, body)


@router.get("/traces/{run_id}")
def get_trace(run_id: str, request: Request, format: str = "json"):
    svc = _state(request)
    if not RUN_ID.match(run_id):
        raise HTTPException(400, "bad run id")
    candidates = [svc.settings.logs_dir / f"trace-{run_id}.jsonl", svc.sample.trace_path(run_id)]
    path = next((p for p in candidates if Path(p).exists()), None)
    if path is None:
        raise HTTPException(404, f"no trace for {run_id}")
    if format == "jsonl":
        return PlainTextResponse(Path(path).read_text(encoding="utf-8"), media_type="application/x-ndjson")
    return {"run_id": run_id, "events": read_trace(path)}


@router.get("/runs")
def list_runs(request: Request) -> list[dict[str, Any]]:
    return [{"run_id": r["run_id"], "question": r.get("question"), "status": r["status"]}
            for r in _state(request).registry.runs.values()]
