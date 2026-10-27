"""Live activity: what the agent is doing right now, kept in memory for `GET /activity`.

Fed by the Orchestrator (`start` / `finish`) and by a listener on `Trace.emit` (`on_event`). It keeps only
what the trace already holds after secret masking (event names, agent names, short summaries, counts); no
prompt text, no keys. Bounded by construction: 12 recent events per active run, 10 finished runs.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from app.adapters.model import mask_secrets

RECENT_EVENTS = 12
RECENT_RUNS = 10
SUMMARY_CHARS = 200
STAGES = ("Planner", "Investigator", "Verifier", "Writer")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


class _Run:
    def __init__(self, run_id: str, kind: str, question: str):
        self.run_id, self.kind, self.question = run_id, kind, mask_secrets(question)[:500]
        self.started = time.time()
        self.stage: str | None = None
        self.events = self.queries = self.blocks = self.retries = 0
        self.recent: deque[dict[str, Any]] = deque(maxlen=RECENT_EVENTS)
        self.call_log: list[dict[str, Any]] = []  # the run's ModelAdapter.call_log (shared list, read-only here)


class ActivityTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, _Run] = {}
        self._recent: deque[dict[str, Any]] = deque(maxlen=RECENT_RUNS)
        self._report_started: float | None = None

    # ---- runs ------------------------------------------------------------------------------------
    def start(self, run_id: str, kind: str, question: str) -> None:
        with self._lock:
            self._active[run_id] = _Run(run_id, kind, question)

    def attach_model(self, run_id: str, call_log: list[dict[str, Any]]) -> None:
        with self._lock:
            run = self._active.get(run_id)
            if run:
                run.call_log = call_log

    def on_event(self, run_id: str, rec: dict[str, Any]) -> None:
        if rec.get("event") == "wm_mutation":
            return
        with self._lock:
            run = self._active.get(run_id)
            if run is None:
                return
            run.events += 1
            run.queries += rec["event"] == "query"
            run.blocks += rec["event"] == "block"
            run.retries += rec["event"] == "retry"
            if rec.get("agent_name") in STAGES:
                run.stage = rec["agent_name"]
            run.recent.append({"event": rec["event"], "agent": rec.get("agent_name", ""),
                               "action": rec.get("action", ""),
                               "summary": (rec.get("output_summary") or rec.get("input_summary") or "")[:SUMMARY_CHARS],
                               "status": rec.get("status", "success"), "at": rec.get("timestamp", "")})

    def finish(self, run_id: str, status: str) -> None:
        with self._lock:
            run = self._active.pop(run_id, None)
            if run is None:
                return
            now = time.time()
            self._recent.appendleft({"run_id": run.run_id, "kind": run.kind, "question": run.question,
                                     "status": status, "elapsed_s": round(now - run.started, 1),
                                     "finished_at": _iso(now)})

    # ---- report generation guard -----------------------------------------------------------------
    def begin_report(self) -> bool:
        """Claim the single report slot; False when a report is already being generated."""
        with self._lock:
            if self._report_started is not None:
                return False
            self._report_started = time.time()
            return True

    def end_report(self) -> None:
        with self._lock:
            self._report_started = None

    def report_job(self) -> dict[str, Any] | None:
        with self._lock:
            return self._report_job_locked(time.time())

    def _report_job_locked(self, now: float) -> dict[str, Any] | None:
        if self._report_started is None:
            return None
        return {"started_at": _iso(self._report_started), "elapsed_s": round(now - self._report_started, 1)}

    # ---- snapshot --------------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            active = []
            for run in self._active.values():
                calls = list(run.call_log)
                answered = next((c for c in reversed(calls) if c.get("ok")), None)
                # routed_model is only reported by a live provider; offline modes fall back to the requested id
                model = (answered.get("routed_model") or answered.get("requested_model")) if answered else None
                active.append({
                    "run_id": run.run_id, "kind": run.kind, "question": run.question,
                    "started_at": _iso(run.started), "elapsed_s": round(now - run.started, 1), "stage": run.stage,
                    "counts": {"events": run.events, "queries": run.queries, "model_calls": len(calls),
                               "blocks": run.blocks, "retries": run.retries},
                    "model": model, "recent_events": list(run.recent)})
            return {"now": _iso(now), "active": active, "recent": list(self._recent),
                    "report_job": self._report_job_locked(now)}
