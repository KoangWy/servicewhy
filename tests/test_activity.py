"""Live activity (`GET /activity`), the single-report guard and run id validation. No network, no Docker."""
import json
import re
import threading
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.activity import ActivityTracker
from app.adapters.fake_model import respond
from app.adapters.model import ModelAdapter
from app.main import create_app
from app.orchestrator import Orchestrator
from app.runtime import data_adapter
from conftest import DEMO

TOKENISH = re.compile(r"sk-[A-Za-z0-9]{8,}|Bearer\s+\S+|api[_-]?key", re.I)


class Gate:
    """A fake model that parks on its Nth call until released, so a run can be observed in flight."""

    def __init__(self, park_at: int = 2, fail: bool = False):
        self.park_at, self.fail, self.calls = park_at, fail, 0
        self.reached, self.release = threading.Event(), threading.Event()

    def __call__(self, role, system, prompt):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model exploded")
        if self.calls == self.park_at:
            self.reached.set()
            assert self.release.wait(30), "gate never released"
        return respond(role, system, prompt)


def gated(client, settings, gate):
    svc = client.app.state.svc
    svc.orchestrator = Orchestrator(settings, lambda: data_adapter(settings),
                                    lambda s: ModelAdapter("fake", session_id=s, fake=gate), activity=svc.activity)


def in_thread(fn, *args, **kw):
    box = {}

    def target():
        box["r"] = fn(*args, **kw)
    t = threading.Thread(target=target)
    t.start()
    return t, box


def test_activity_shows_a_run_in_flight_then_moves_it_to_recent(client, settings):
    gate = Gate()
    gated(client, settings, gate)
    t, box = in_thread(client.post, "/run", json={"run_id": "ui-1a2b3c4d", "input": {"query": DEMO}})
    assert gate.reached.wait(30)
    act = client.get("/activity").json()
    assert act["recent"] == [] and act["report_job"] is None and act["now"].endswith("Z")
    (run,) = act["active"]
    assert run["run_id"] == "ui-1a2b3c4d" and run["kind"] == "ask" and run["question"] == DEMO
    assert run["stage"] == "Verifier" and run["counts"]["model_calls"] == 2 and run["counts"]["events"] >= 1
    assert run["model"] and run["elapsed_s"] >= 0 and run["started_at"].endswith("Z")
    evs = run["recent_events"]
    assert 1 <= len(evs) <= 12 and evs[0]["event"] == "run_start"
    assert all(e["event"] != "wm_mutation" and len(e["summary"]) <= 200 for e in evs)
    assert set(evs[-1]) == {"event", "agent", "action", "summary", "status", "at"}
    gate.release.set()
    t.join(60)
    assert box["r"].status_code == 200
    act = client.get("/activity").json()
    assert act["active"] == []
    (done,) = act["recent"]
    assert done["run_id"] == "ui-1a2b3c4d" and done["status"] == "success" and done["finished_at"].endswith("Z")


def test_final_counts_match_the_trace(client, settings):
    tracker = client.app.state.svc.activity
    seen = {}
    orig = tracker.finish

    def spy(run_id, status):
        seen.update(tracker.snapshot()["active"][0])
        orig(run_id, status)
    tracker.finish = spy
    client.post("/run", json={"run_id": "counts-1", "input": {"query": DEMO}})
    events = client.get("/traces/counts-1").json()["events"]
    c = seen["counts"]
    assert c["events"] == len([e for e in events if e["event"] != "wm_mutation"])
    assert c["queries"] == len([e for e in events if e["event"] == "query"])
    assert c["blocks"] == len([e for e in events if e["event"] == "block"])
    assert c["retries"] == len([e for e in events if e["event"] == "retry"])
    assert seen["stage"] == "Writer"


def test_a_failing_run_lands_in_recent_with_status_error(client, settings):
    gated(client, settings, Gate(fail=True))
    r = client.post("/run", json={"run_id": "boom-1", "input": {"query": DEMO}})
    assert r.status_code == 502
    act = client.get("/activity").json()
    assert act["active"] == []
    assert [(x["run_id"], x["status"]) for x in act["recent"]] == [("boom-1", "error")]


def test_a_crash_outside_the_error_handler_still_finishes_the_run(settings):
    tracker = ActivityTracker()
    orch = Orchestrator(settings, lambda: data_adapter(settings), activity=tracker)

    def bad_trace(*a, **k):
        raise KeyboardInterrupt
    import app.orchestrator as mod
    orig, mod.Trace = mod.Trace, bad_trace
    try:
        with pytest.raises(KeyboardInterrupt):
            orch.run(DEMO, run_id="crash-1")
    finally:
        mod.Trace = orig
    snap = tracker.snapshot()
    assert snap["active"] == [] and snap["recent"][0]["status"] == "error"


def test_recent_is_bounded_and_newest_first():
    t = ActivityTracker()
    for i in range(15):
        t.start(f"r{i}", "ask", "q")
        t.finish(f"r{i}", "success")
    ids = [r["run_id"] for r in t.snapshot()["recent"]]
    assert len(ids) == 10 and ids[0] == "r14" and ids[-1] == "r5"


def test_recent_events_are_bounded_and_skip_world_model_mutations():
    t = ActivityTracker()
    t.start("r", "ask", "q")
    for i in range(30):
        t.on_event("r", {"event": "query", "agent_name": "Investigator", "action": "run_query",
                         "output_summary": "x" * 500, "timestamp": "2026-10-27T19:58:03Z"})
        t.on_event("r", {"event": "wm_mutation", "agent_name": "Planner", "action": "put_hypothesis"})
    run = t.snapshot()["active"][0]
    assert len(run["recent_events"]) == 12 and all(len(e["summary"]) == 200 for e in run["recent_events"])
    assert run["stage"] == "Investigator" and run["counts"]["events"] == 30 and run["model"] is None


def test_model_is_the_routed_model_of_the_latest_successful_call():
    t = ActivityTracker()
    t.start("r", "ask", "q")
    t.attach_model("r", [{"ok": True, "routed_model": "nemotron", "requested_model": "auto"},
                         {"ok": True, "routed_model": "gpt-x", "requested_model": "auto"},
                         {"ok": False, "routed_model": None, "requested_model": "auto"}])
    run = t.snapshot()["active"][0]
    assert run["model"] == "gpt-x" and run["counts"]["model_calls"] == 3


def test_kind_is_report_for_report_runs_and_drilldown_for_drilldowns(client, settings):
    tracker = client.app.state.svc.activity
    kinds = {}
    orig = tracker.start
    tracker.start = lambda run_id, kind, q: (kinds.__setitem__(run_id, kind), orig(run_id, kind, q))
    rid = client.post("/reports", json={}).json()["report_id"]
    assert kinds == {f"{rid}-1": "report", f"{rid}-2": "report"}
    fid = client.get(f"/reports/{rid}").json()["findings"][0]["id"]
    run = client.post(f"/findings/{fid}/drilldown", json={}).json()["run"]
    assert kinds[run["run_id"]] == "drilldown"
    ask = client.post("/run", json={"input": {"query": DEMO}}).json()
    assert kinds[ask["run_id"]] == "ask"
    assert [r["kind"] for r in client.get("/activity").json()["recent"]][:2] == ["ask", "drilldown"]


def test_second_report_during_a_generation_gets_409_and_starts_no_model_call(client, settings):
    gate = Gate()
    gated(client, settings, gate)
    t, box = in_thread(client.post, "/reports", json={})
    assert gate.reached.wait(30)
    calls = gate.calls
    r = client.post("/reports", json={})
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "error" and body["error"] == {
        "type": "ReportInProgress", "message": "a report is already being generated", "recoverable": True}
    assert body["report_job"]["started_at"].endswith("Z") and body["report_job"]["elapsed_s"] >= 0
    assert gate.calls == calls
    act = client.get("/activity").json()
    assert act["report_job"]["started_at"] == body["report_job"]["started_at"]
    assert [a["kind"] for a in act["active"]] == ["report"]
    gate.release.set()
    t.join(120)
    assert box["r"].status_code == 200
    assert client.get("/activity").json()["report_job"] is None
    assert len(client.get("/reports").json()) == 1
    assert client.post("/reports", json={}).status_code == 200  # the guard is released


def test_report_job_clears_after_a_failed_generation(client, monkeypatch):
    from app.report import generator

    def boom(*a, **k):
        raise RuntimeError("generator failed")
    monkeypatch.setattr(generator, "generate", boom)
    lenient = TestClient(client.app, raise_server_exceptions=False)
    assert lenient.post("/reports", json={}).status_code == 500
    assert client.get("/activity").json()["report_job"] is None
    monkeypatch.undo()
    assert client.post("/reports", json={}).status_code == 200


def test_report_job_clears_when_every_run_errors(client, settings):
    gated(client, settings, Gate(fail=True))
    rep = client.post("/reports", json={}).json()
    assert rep["status"] == "error"
    act = client.get("/activity").json()
    assert act["report_job"] is None and {r["status"] for r in act["recent"]} == {"error"}


@pytest.mark.parametrize("run_id", ["ui-1a2b3c4d", "demo-001", "a.b_c-9", "x" * 64])
def test_valid_run_ids_are_accepted(client, run_id):
    r = client.post("/run", json={"run_id": run_id, "input": {"query": "Is the kitchen slow on Saturdays?"}})
    assert r.status_code == 200 and r.json()["run_id"] == run_id


@pytest.mark.parametrize("run_id", ["../x", "a/b", "x" * 65, "has space", "", "ünï", "a\\b"])
def test_invalid_run_ids_are_rejected_with_the_structured_error(client, settings, run_id):
    r = client.post("/run", json={"run_id": run_id, "input": {"query": DEMO}})
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "error" and body["error"]["type"] == "InvalidRunId" and body["error"]["recoverable"]
    assert not list(settings.logs_dir.glob("*")) if settings.logs_dir.exists() else True


def test_trace_endpoint_serves_the_events_so_far_while_the_run_is_in_flight(client, settings):
    gate = Gate()
    gated(client, settings, gate)
    t, box = in_thread(client.post, "/run", json={"run_id": "live-1", "input": {"query": DEMO}})
    assert gate.reached.wait(30)
    events = client.get("/traces/live-1").json()["events"]
    assert events[0]["event"] == "run_start" and events[-1]["event"] != "run_end"
    assert len(client.get("/traces/live-1?format=jsonl").text.splitlines()) >= len(events)
    gate.release.set()
    t.join(60)
    assert client.get("/traces/live-1").json()["events"][-1]["event"] == "run_end"
    assert client.get("/traces/never-ran").status_code == 404


def test_trace_of_an_empty_or_half_written_file(client, settings):
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "trace-empty.jsonl").write_text("")
    assert client.get("/traces/empty").json() == {"run_id": "empty", "events": []}
    first = json.dumps({"schema_version": 1, "event": "run_start", "run_id": "half"})
    (settings.logs_dir / "trace-half.jsonl").write_text(first + "\n" + first[:20])
    assert len(client.get("/traces/half").json()["events"]) == 1


def test_activity_never_carries_secrets(client, settings):
    gate = Gate()
    gated(client, settings, gate)
    t, _ = in_thread(client.post, "/run", json={"input": {"query": "Is the kitchen slow on Saturdays?"}})
    assert gate.reached.wait(30)
    mid = client.get("/activity").text
    gate.release.set()
    t.join(60)
    assert not TOKENISH.search(mid) and not TOKENISH.search(client.get("/activity").text)


def test_activity_is_empty_in_sample_mode(settings):
    app = create_app(replace(settings, sample_mode=True))
    r = TestClient(app).get("/activity")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == [] and body["recent"] == [] and body["report_job"] is None and body["now"].endswith("Z")
